"""Warnings about where the study folder lives: the patterns, the messages, and "never blocks".

Nothing here needs a network drive: the operating-system questions (the list of mounts, the Windows
drive type, the environment) are passed in, and the path rules are those of the platform asked
about, so every case runs on every platform.
"""

import os
import sys

import pytest

from exprand import Finding, folder_warnings
from exprand import placement as pl

NO_ENV: dict[str, str] = {}
LOCAL_MOUNTS = [("/", "ext4")]


def local_drives(drive):
    return False


# -- Windows: UNC paths and mapped drives -------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        (r"\\server\share\study", True),
        ("//server/share/study", True),
        (r"\\?\UNC\server\share\study", True),
        (r"\\?\unc\server\share\study", True),
        (r"\\?\C:\Users\ana\study", False),
        (r"\\.\COM1", False),
        (r"C:\Users\ana\study", False),
        ("/home/ana/study", False),
        ("study", False),
        ("", False),
    ],
)
def test_unc_paths(text, expected):
    assert pl.is_unc(text) is expected


def test_a_unc_path_is_a_network_share():
    found = folder_warnings(
        r"\\server\share\study", platform="win32", environ=NO_ENV, remote_drive=local_drives
    )
    assert found == [Finding("network", "unc")]


def test_a_mapped_network_drive_is_found_by_asking_windows_about_the_drive_letter():
    asked = []

    def remote(drive):
        asked.append(drive)
        return drive == "Z:"

    found = folder_warnings(
        r"Z:\studies\one", platform="win32", environ=NO_ENV, remote_drive=remote
    )
    assert found == [Finding("network", "mapped-drive", "Z:")]
    assert set(asked) == {"Z:"}
    assert (
        folder_warnings(r"C:\studies\one", platform="win32", environ=NO_ENV, remote_drive=remote)
        == []
    )


def test_a_failing_drive_query_is_not_an_error_and_not_a_warning():
    def broken(drive):
        raise OSError("the drive went away")

    assert folder_warnings(r"Z:\s", platform="win32", environ=NO_ENV, remote_drive=broken) == []


# -- Linux and macOS: the file system under the folder ------------------------------------------
MOUNTINFO = r"""22 28 0:21 / /sys rw,nosuid,nodev,noexec,relatime shared:7 - sysfs sysfs rw
28 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw,errors=remount-ro
36 28 98:0 /mnt1 /mnt/my\040disk rw,noatime master:1 - ext3 /dev/root rw,errors=continue
40 28 0:45 / /mnt/share rw,relatime shared:50 - cifs //server/share rw,vers=3.1.1
41 28 0:46 / /home/ana/nas rw,relatime - nfs4 nas:/export rw,vers=4.2
42 41 8:17 / /home/ana/nas/scratch rw,relatime shared:9 - ext4 /dev/sdb1 rw
not a mountinfo line

37 28 0:99 / /mnt/broken rw
"""

MOUNT_OUTPUT = """/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)
//ana@nas.local/share on /Volumes/share (smbfs, nodev, nosuid, mounted by ana)
nas:/export on /Volumes/export (nfs, nodev, nosuid, mounted by ana)
/dev/disk4s1 on /Volumes/Backup on Disk (hfs, local, nodev, nosuid, journaled)
map auto_home on /System/Volumes/Data/home (autofs, automounted, nobrowse)
this line is not a mount
"""


def test_mountinfo_is_parsed_with_escaped_spaces_and_bad_lines_skipped():
    assert pl.parse_mountinfo(MOUNTINFO) == [
        ("/sys", "sysfs"),
        ("/", "ext4"),
        ("/mnt/my disk", "ext3"),
        ("/mnt/share", "cifs"),
        ("/home/ana/nas", "nfs4"),
        ("/home/ana/nas/scratch", "ext4"),
    ]


def test_the_output_of_mount_on_macos_is_parsed():
    assert pl.parse_mount_output(MOUNT_OUTPUT) == [
        ("/", "apfs"),
        ("/Volumes/share", "smbfs"),
        ("/Volumes/export", "nfs"),
        ("/Volumes/Backup on Disk", "hfs"),
        ("/System/Volumes/Data/home", "autofs"),
    ]


MOUNTS = pl.parse_mountinfo(MOUNTINFO)


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/mnt/share/study", "cifs"),
        ("/mnt/share", "cifs"),
        ("/home/ana/nas/study", "nfs4"),
        ("/home/ana/nas/scratch/study", None),  # something local is mounted on top of the share
        ("/mnt/shared/study", None),  # a longer name, not a folder of the mount
        ("/mnt/my disk/study", None),
        ("/home/ana/study", None),
        ("/", None),
    ],
)
def test_the_file_system_that_holds_a_path(path, expected):
    assert pl.network_filesystem(path, MOUNTS) == expected


def test_no_mounts_known_means_no_network_file_system():
    assert pl.network_filesystem("/anything", []) is None


def test_the_case_of_the_path_only_matters_where_the_file_system_ignores_it():
    mounts = [("/Volumes/share", "smbfs")]
    assert pl.network_filesystem("/volumes/SHARE/study", mounts, fold=True) == "smbfs"
    assert pl.network_filesystem("/volumes/SHARE/study", mounts) is None


@pytest.mark.parametrize("fs", sorted(pl.NETWORK_FILESYSTEMS))
def test_every_network_file_system_is_recognised(fs):
    assert pl.network_filesystem("/data/x", [("/", "ext4"), ("/data", fs)]) == fs


@pytest.mark.parametrize(
    "fs", ["ext4", "xfs", "btrfs", "tmpfs", "overlay", "apfs", "9p", "fuse.ntfs-3g"]
)
def test_local_file_systems_are_not_network_file_systems(fs):
    assert pl.network_filesystem("/data/x", [("/", fs)]) is None


def test_a_folder_on_an_nfs_mount_is_a_network_folder():
    found = folder_warnings("/home/ana/nas/study", platform="linux", environ=NO_ENV, mounts=MOUNTS)
    assert found == [Finding("network", "filesystem", "nfs4")]
    found = folder_warnings(
        "/Volumes/share/study",
        platform="darwin",
        environ=NO_ENV,
        mounts=[("/volumes/share", "smbfs")],
    )
    assert found == [Finding("network", "filesystem", "smbfs")]


def test_reading_the_mounts_never_raises():
    assert pl.read_mounts("freebsd") == []
    assert pl.read_mounts("win32") == []


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc/self/mountinfo")
def test_the_mounts_of_this_linux_computer_are_listed():
    mounts = pl.read_mounts("linux")
    assert mounts and all(isinstance(m, tuple) and len(m) == 2 for m in mounts)
    assert any(point == "/" for point, _ in mounts)


# -- the usual folders of the sync services ----------------------------------------------------
@pytest.mark.parametrize(
    "text, service",
    [
        (r"C:\Users\ana\OneDrive\Documents\study", "OneDrive"),
        (r"C:\Users\ana\OneDrive - Universidade Federal do Rio de Janeiro\estudo", "OneDrive"),
        ("/Users/ana/Library/CloudStorage/OneDrive-Contoso/study", "OneDrive"),
        ("/home/ana/onedrive/study", "OneDrive"),
        (r"C:\Users\ana\Dropbox\study", "Dropbox"),
        ("/home/ana/Dropbox (Personal)/study", "Dropbox"),
        ("/Users/ana/Library/CloudStorage/Dropbox-Contoso/study", "Dropbox"),
        ("/home/ana/Google Drive/study", "Google Drive"),
        (r"G:\My Drive\study", "Google Drive"),
        (r"G:\Meu Drive\estudo", "Google Drive"),
        (
            "/Users/ana/Library/CloudStorage/GoogleDrive-ana@example.com/My Drive/study",
            "Google Drive",
        ),
        (r"C:\Users\ana\iCloudDrive\study", "iCloud Drive"),
        ("/Users/ana/Library/Mobile Documents/com~apple~CloudDocs/study", "iCloud Drive"),
        ("/Users/ana/Library/CloudStorage/Box-Box/study", "cloud-storage"),
    ],
)
def test_a_folder_inside_a_sync_service_is_found(text, service):
    assert pl.synced_service(text) == service


@pytest.mark.parametrize(
    "text",
    [
        "/home/ana/Documents/study",
        r"C:\Users\ana\Documents\study",
        "/home/ana/Dropbox analysis/study",  # an ordinary folder that starts with the name
        "/home/ana/onedrive_backup/study",
        "/home/ana/OneDrive2/study",
        "/srv/mydrive/study",
        "/home/ana/Library/Documents/study",
        "/home/ana/CloudStorage/study",  # not under a Library folder
        "",
    ],
)
def test_ordinary_folders_are_not_sync_folders(text):
    assert pl.synced_service(text) is None


def test_a_onedrive_folder_with_a_custom_name_is_found_through_the_environment():
    env = {"OneDriveCommercial": r"D:\Cloud\Work"}
    assert pl.synced_service(r"D:\Cloud\Work\study", env) == "OneDrive"
    assert pl.synced_service(r"d:\cloud\work\study", env) == "OneDrive"  # Windows ignores case
    assert pl.synced_service(r"D:\Cloud\Workshop\study", env) is None
    assert pl.synced_service(r"D:\Cloud\Work\study", {"OneDrive": ""}) is None
    assert pl.synced_service(r"D:\Cloud\Work\study") is None


def test_a_synced_folder_is_found_on_the_path_as_given_or_after_following_a_link(tmp_path):
    inside = tmp_path / "Dropbox" / "study"
    inside.mkdir(parents=True)
    link = tmp_path / "shortcut"
    try:
        os.symlink(inside, link, target_is_directory=True)
    except (OSError, NotImplementedError):  # Windows without the right to make links
        pytest.skip("cannot make a symbolic link here")
    system = sys.platform
    found = folder_warnings(
        link, platform=system, environ=NO_ENV, mounts=LOCAL_MOUNTS, remote_drive=local_drives
    )
    assert found == [Finding("synced", "Dropbox")]


# -- putting them together ---------------------------------------------------------------------
def test_a_local_folder_gets_no_warning(tmp_path):
    for system in ("linux", "darwin", "win32"):
        found = folder_warnings(
            tmp_path / "study",
            platform=system,
            environ=NO_ENV,
            mounts=LOCAL_MOUNTS,
            remote_drive=local_drives,
        )
        assert found == [], system


def test_a_folder_that_does_not_exist_yet_is_judged_by_its_path():
    found = folder_warnings(
        "/home/ana/Dropbox/new/study", platform="linux", environ=NO_ENV, mounts=LOCAL_MOUNTS
    )
    assert found == [Finding("synced", "Dropbox")]


def test_a_network_share_that_is_also_synced_gives_both_warnings_network_first():
    found = folder_warnings(
        "/mnt/share/Dropbox/study", platform="linux", environ=NO_ENV, mounts=MOUNTS
    )
    assert [f.kind for f in found] == ["network", "synced"]


@pytest.mark.parametrize("value", ["1", "yes", "true", "on", "anything"])
def test_the_warning_can_be_silenced(value):
    env = {pl.SILENCE_VARIABLE: value}
    found = folder_warnings(
        "/mnt/share/Dropbox/study", platform="linux", environ=env, mounts=MOUNTS
    )
    assert found == []


@pytest.mark.parametrize("value", ["", "0", "false", "No", " "])
def test_these_values_do_not_silence_it(value):
    env = {pl.SILENCE_VARIABLE: value}
    found = folder_warnings("/mnt/share/study", platform="linux", environ=env, mounts=MOUNTS)
    assert len(found) == 1


def test_the_real_environment_is_used_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv(pl.SILENCE_VARIABLE, "1")
    assert folder_warnings(tmp_path / "Dropbox" / "study") == []
    monkeypatch.delenv(pl.SILENCE_VARIABLE)
    monkeypatch.setattr(pl, "read_mounts", lambda system: LOCAL_MOUNTS)
    monkeypatch.setattr(pl, "windows_drive_is_remote", local_drives)
    assert folder_warnings(tmp_path / "Dropbox" / "study") == [Finding("synced", "Dropbox")]


# -- the words ---------------------------------------------------------------------------------
ALL = [
    Finding("network", "unc"),
    Finding("network", "mapped-drive", "Z:"),
    Finding("network", "filesystem", "nfs4"),
    Finding("synced", "OneDrive"),
    Finding("synced", "Dropbox"),
    Finding("synced", "Google Drive"),
    Finding("synced", "iCloud Drive"),
    Finding("synced", "cloud-storage"),
]


def test_every_finding_has_a_message_in_both_languages_with_no_placeholder_left():
    for finding in ALL:
        for language in ("en", "pt"):
            text = finding.message(language)
            assert text and "{" not in text and "}" not in text, (finding, language)


def test_both_languages_have_the_same_keys():
    assert pl._TEXT["en"].keys() == pl._TEXT["pt"].keys()


def test_the_message_names_what_was_found():
    assert "UNC" in Finding("network", "unc").message()
    assert "Z:" in Finding("network", "mapped-drive", "Z:").message()
    assert "nfs4" in Finding("network", "filesystem", "nfs4").message()
    assert "OneDrive" in Finding("synced", "OneDrive").message()
    assert "Dropbox" in Finding("synced", "Dropbox").message("pt")
    assert "cloud-storage service" in Finding("synced", "cloud-storage").message()


def test_a_language_without_a_translation_gets_english():
    for finding in ALL:
        assert finding.message("es") == finding.message("en")
        assert finding.message("pt") != finding.message("en")


def test_the_messages_advise_and_never_forbid():
    for finding in ALL:
        text = finding.message().lower()
        assert "local" in text and "must not" not in text and "refuse" not in text
