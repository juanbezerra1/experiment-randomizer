"""Where the study folder lives: advice, never a veto.

The lock that stops two programs from drawing the same session is an operating-system file lock. It
is reliable on a local disk but not on every network file system, and a folder that a sync client
(OneDrive, Dropbox, Google Drive, iCloud) watches can end up with a conflicted copy of the log.
:func:`folder_warnings` recognises the common cases so that the command line and the window can
say so. It only ever *advises*: the experimenter may know better, so nothing here stops a draw, and
a folder on a local disk gives no warning at all.

What is recognised, and how:

* **a network share on Windows**: a UNC path (``\\\\server\\share``), or a drive letter that Windows
  reports as a network drive (``GetDriveTypeW``);
* **a network file system on Linux and macOS**: the file system of the mount that holds the folder
  (``/proc/self/mountinfo`` on Linux, the output of ``mount`` on macOS) is NFS, SMB/CIFS, sshfs and
  the like;
* **a synced folder**: a path component that is the usual folder of OneDrive, Dropbox, Google Drive
  or iCloud Drive (``OneDrive - Contoso``, ``Dropbox (Personal)``, ``My Drive``, ``Meu Drive``,
  ``iCloud Drive``...), or a folder under the OneDrive location that Windows publishes in the
  ``OneDrive`` environment variables.

What is not recognised: other sync tools (Box, MEGA, Nextcloud, pCloud...), a sync client set up
on a folder with an ordinary name, and a network drive that the operating system reports as local.
Set ``EXPRAND_NO_LOCATION_WARNING=1`` to silence the warning.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "NETWORK",
    "SILENCE_VARIABLE",
    "SYNCED",
    "Finding",
    "folder_warnings",
    "is_unc",
    "network_filesystem",
    "parse_mount_output",
    "parse_mountinfo",
    "synced_service",
]

NETWORK = "network"
SYNCED = "synced"
SILENCE_VARIABLE = "EXPRAND_NO_LOCATION_WARNING"

# File systems that live on another computer. ``9p`` is left out on purpose: it is also how WSL
# shows the Windows disks, which are local.
NETWORK_FILESYSTEMS = frozenset(
    {
        "nfs", "nfs3", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afpfs", "afs", "ncpfs",
        "ceph", "glusterfs", "lustre", "webdav", "davfs", "fuse.sshfs", "fuse.davfs",
        "fuse.rclone", "fuse.gvfsd-fuse",
    }
)  # fmt: skip

# (service, a path component, matched as a whole and without regard to case)
_SYNC_FOLDERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # "OneDrive", "OneDrive - Contoso", "OneDrive-Contoso" (macOS)
    ("OneDrive", re.compile(r"onedrive(\s*-\s*.+)?", re.IGNORECASE)),
    # "Dropbox", "Dropbox (Personal)", "Dropbox-Contoso" (macOS)
    ("Dropbox", re.compile(r"dropbox(\s*\(.+\)|-.+)?", re.IGNORECASE)),
    # "Google Drive", "GoogleDrive-name@example.com" (macOS), and the root "My Drive" / "Meu Drive"
    ("Google Drive", re.compile(r"google\s?drive(-.+)?|(my|meu)\s+drive", re.IGNORECASE)),
    # "iCloud Drive", "iCloudDrive" (Windows), "com~apple~CloudDocs" (macOS)
    ("iCloud Drive", re.compile(r"icloud\s?drive|com~apple~clouddocs", re.IGNORECASE)),
)
SERVICES = frozenset(name for name, _ in _SYNC_FOLDERS)
_ONEDRIVE_VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
_SEPARATORS = re.compile(r"[\\/]+")


@dataclass(frozen=True)
class Finding:
    """One reason to be careful about the folder.

    ``kind`` is :data:`NETWORK` or :data:`SYNCED`. ``source`` says what was recognised (``unc``,
    ``mapped-drive``, ``filesystem``, a service such as ``OneDrive``, or ``cloud-storage``) and
    ``detail`` adds the drive letter or the file system type where there is one.
    """

    kind: str
    source: str
    detail: str = ""

    def message(self, language: str = "en") -> str:
        """The warning in ``language`` (English if there is no translation of it)."""
        text = _TEXT.get(language) or _TEXT["en"]
        if self.kind == SYNCED:
            service = self.source if self.source in SERVICES else text["cloud-storage"]
            return text[SYNCED].format(service=service)
        where = text.get(self.source, text["filesystem"]).format(detail=self.detail)
        return text[NETWORK].format(where=where)


# The window and the command line use these. They live here, not in ``i18n.py``, so that a language
# that has no translation falls back to English instead of breaking the window.
_TEXT: dict[str, dict[str, str]] = {
    "en": {
        NETWORK: (
            "The study folder is on {where}. The file lock that keeps two programs from drawing "
            "the same session is not reliable on every network file system, so two computers "
            "could draw the same session. Keep the study on a local disk, or make sure that only "
            "one computer draws."
        ),
        SYNCED: (
            "The study folder is in a folder synced by {service}. A sync client can create "
            "conflicted copies of the log when two computers write, or copy it half written. "
            "Draw on a local folder and copy the result, or pause the sync while drawing."
        ),
        "unc": "a network share (UNC path)",
        "mapped-drive": "a mapped network drive ({detail})",
        "filesystem": "a network file system ({detail})",
        "cloud-storage": "a cloud-storage service",
    },
    "pt": {
        NETWORK: (
            "A pasta do estudo está em {where}. O bloqueio de arquivo que impede dois programas "
            "de sortearem a mesma sessão não é confiável em todo sistema de arquivos de rede, "
            "então dois computadores poderiam sortear a mesma sessão. Deixe o estudo num disco "
            "local ou garanta que só um computador sorteie."
        ),
        SYNCED: (
            "A pasta do estudo está numa pasta sincronizada pelo {service}. Um cliente de "
            "sincronização pode criar cópias em conflito do registro quando dois computadores "
            "escrevem, ou copiá-lo pela metade. Sorteie numa pasta local e copie o resultado, "
            "ou pause a sincronização enquanto sorteia."
        ),
        "unc": "um compartilhamento de rede (caminho UNC)",
        "mapped-drive": "uma unidade de rede mapeada ({detail})",
        "filesystem": "um sistema de arquivos de rede ({detail})",
        "cloud-storage": "serviço de armazenamento em nuvem",
    },
}


# -- recognising a path (pure functions on text, the same on every platform) -------------------
def _components(text: str) -> list[str]:
    return [part for part in _SEPARATORS.split(text) if part]


def is_unc(text: str) -> bool:
    r"""True for a Windows UNC path: ``\\server\share``, ``//server/share``, ``\\?\UNC\...``."""
    norm = text.replace("/", "\\")
    if norm.startswith("\\\\?\\"):
        return norm[4:8].upper() == "UNC\\"
    if norm.startswith("\\\\.\\"):  # a local device, not a share
        return False
    return norm.startswith("\\\\")


def _is_under(text: str, root: str) -> bool:
    parts, base = _components(text.lower()), _components(root.lower())
    return bool(base) and parts[: len(base)] == base


def synced_service(text: str, environ: Mapping[str, str] | None = None) -> str | None:
    """The sync service whose folder ``text`` is in (``OneDrive``...), or ``cloud-storage``."""
    parts = _components(text)
    for part in parts:
        for service, pattern in _SYNC_FOLDERS:
            if pattern.fullmatch(part):
                return service
    lowered = [part.lower() for part in parts]
    for first, second in zip(lowered, lowered[1:], strict=False):
        if first == "library" and second == "mobile documents":
            return "iCloud Drive"
        if first == "library" and second == "cloudstorage":  # macOS: any File Provider service
            return "cloud-storage"
    for variable in _ONEDRIVE_VARIABLES:
        root = (environ or {}).get(variable, "")
        if root and _is_under(text, root):
            return "OneDrive"
    return None


def parse_mountinfo(text: str) -> list[tuple[str, str]]:
    """``(mount point, file system type)`` pairs from ``/proc/self/mountinfo``."""
    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if "-" not in fields[6:]:
            continue
        sep = fields.index("-", 6)
        if len(fields) > sep + 1:
            mounts.append((_unescape_mount(fields[4]), fields[sep + 1]))
    return mounts


def _unescape_mount(text: str) -> str:
    """``/proc`` writes a space as ``\\040`` (and a tab, a newline and a backslash alike)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)


_MOUNT_LINE = re.compile(r"^(?P<source>.+?) on (?P<point>/.*?) \((?P<fs>[^,)]+)")


def parse_mount_output(text: str) -> list[tuple[str, str]]:
    """``(mount point, file system type)`` pairs from the output of ``mount`` on macOS."""
    mounts = []
    for line in text.splitlines():
        found = _MOUNT_LINE.match(line)
        if found:
            mounts.append((found.group("point"), found.group("fs").strip()))
    return mounts


def network_filesystem(
    text: str, mounts: Sequence[tuple[str, str]], fold: bool = False
) -> str | None:
    """The type of the network file system that holds ``text``, or ``None``.

    The mount that holds a path is the longest mount point that is a prefix of it, so a local
    folder under an NFS mount that has something else mounted on top of it is not misreported.
    """
    parts = _components(text.lower() if fold else text)
    best: tuple[int, str] | None = None
    for point, fs in mounts:
        base = _components(point.lower() if fold else point)
        if parts[: len(base)] == base and (best is None or len(base) > best[0]):
            best = (len(base), fs)
    if best is not None and best[1].lower() in NETWORK_FILESYSTEMS:
        return best[1]
    return None


# -- asking the operating system (each can be replaced, so that tests need no network drive) ---
def read_mounts(platform: str) -> list[tuple[str, str]]:
    """The mounted file systems of this computer; empty if they cannot be listed."""
    try:
        if platform.startswith("linux"):
            with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as handle:
                return parse_mountinfo(handle.read())
        if platform == "darwin":  # pragma: no cover - macOS only
            done = subprocess.run(
                ["/sbin/mount"], capture_output=True, text=True, timeout=5, check=False
            )
            return parse_mount_output(done.stdout)
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def windows_drive_is_remote(drive: str) -> bool:  # pragma: no cover - needs Windows
    """True if Windows says that ``drive`` (``Z:``) is a network drive (``DRIVE_REMOTE`` is 4)."""
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    return bool(kernel32.GetDriveTypeW(drive + "\\") == 4)


# -- the one function the rest of the program uses ---------------------------------------------
def folder_warnings(
    directory: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    mounts: Sequence[tuple[str, str]] | None = None,
    remote_drive: Callable[[str], bool] | None = None,
) -> list[Finding]:
    """Reasons to be careful about drawing in ``directory``; empty for an ordinary local folder.

    The path is looked at as it was given and with symbolic links resolved (a link from a local
    folder into Dropbox is a Dropbox folder). ``environ``, ``platform``, ``mounts`` and
    ``remote_drive`` (a function from a drive such as ``Z:`` to a bool) stand in for the real
    environment, operating system, list of mounts and Windows drive query; they exist for tests.
    Nothing is raised: if the system cannot be asked, the answer is "no warning".
    """
    env = os.environ if environ is None else environ
    if env.get(SILENCE_VARIABLE, "").strip().lower() not in ("", "0", "false", "no"):
        return []
    system = sys.platform if platform is None else platform
    paths = ntpath if system == "win32" else posixpath  # the path rules of the system asked about
    given = paths.abspath(os.fspath(directory))
    candidates = [given]
    try:
        real = paths.realpath(given)
    except OSError:  # pragma: no cover - a path the platform cannot resolve
        real = given
    if real != given:
        candidates.append(real)

    findings: list[Finding] = []
    network = _network_finding(candidates, system, mounts, remote_drive)
    if network is not None:
        findings.append(network)
    for text in candidates:
        service = synced_service(text, env)
        if service is not None:
            findings.append(Finding(SYNCED, service))
            break
    return findings


def _network_finding(
    candidates: Sequence[str],
    system: str,
    mounts: Sequence[tuple[str, str]] | None,
    remote_drive: Callable[[str], bool] | None,
) -> Finding | None:
    if system == "win32":
        query = remote_drive or windows_drive_is_remote
        for text in candidates:
            if is_unc(text):
                return Finding(NETWORK, "unc")
            drive = ntpath.splitdrive(text)[0]
            try:
                if drive and not drive.startswith("\\\\") and query(drive):
                    return Finding(NETWORK, "mapped-drive", drive)
            except OSError:  # pragma: no cover - the drive vanished while we asked
                continue
        return None
    known = read_mounts(system) if mounts is None else mounts
    fold = system == "darwin"
    for text in candidates:
        fs = network_filesystem(text, known, fold)
        if fs is not None:
            return Finding(NETWORK, "filesystem", fs)
    return None
