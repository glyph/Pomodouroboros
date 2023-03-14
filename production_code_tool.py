"""
Future work:

- integrate cocoapods
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum, auto
from os import environ
from typing import (
    AsyncIterable,
    Awaitable,
    Coroutine,
    Deque,
    Iterable,
    Mapping,
    Sequence,
    TypeVar,
)

from packaging.tags import sys_tags
from wheel_filename import ParsedWheelFilename, parse_wheel_filename

from twisted.internet.defer import Deferred, DeferredSemaphore
from twisted.internet.interfaces import IReactorProcess
from twisted.internet.utils import getProcessOutputAndValue
from twisted.python.filepath import FilePath
from twisted.python.procutils import which


@dataclass
class ProcessResult:
    """
    The result of running a process to completion.
    """

    status: int
    output: bytes
    invocation: Invocation

    def check(self) -> None:
        """
        make sure that this process didn't exit with error
        """
        if self.status != 0:
            raise RuntimeError(
                f"process {self.invocation.executable} {self.invocation.argv} exited with error {self.status}\n{self.output.decode('utf-8', 'replace')}"
            )


@dataclass
class Invocation:
    """
    A full command-line to be invoked.
    """

    executable: str
    argv: Sequence[str]

    async def __call__(
        self, *, env: Mapping[str, str] = environ
    ) -> ProcessResult:
        """
        Run the subprocess asynchronously.
        """
        output, value = await getProcessOutputAndValue(
            self.executable, self.argv, env
        )
        return ProcessResult(value, output, self)


@dataclass
class Command:
    """
    A command is a reference to a potential executable on $PATH that can be
    run.
    """

    name: str

    def __getitem__(self, argv: str | tuple[str, ...]) -> Invocation:
        """ """
        return Invocation(which(self.name)[0], argv)

    async def __call__(
        self, *args: str, env: Mapping[str, str] = environ
    ) -> ProcessResult:
        """
        Immedately run.
        """
        return await self[args](env=env)


@dataclass
class SyntaxSugar:
    """
    Syntax sugar for running subprocesses.

    Use like::

        await c.ls()
        await c["docker-compose"]("--help")

    """

    #     reactor: IReactorProcess

    def __getitem__(self, name) -> Command:
        """ """
        return Command(name)

    def __getattr__(self, name) -> Command:
        """ """
        return Command(name)


# from twisted.internet import reactor
c = SyntaxSugar()


class KnownArchitecture(StrEnum):
    x86_64 = auto()
    arm64 = auto()
    universal2 = auto()
    purePython = auto()


@dataclass(frozen=True)
class PlatformSpecifics:
    """ """

    os: str
    major: int
    minor: int
    architecture: KnownArchitecture


def specifics(pwf: ParsedWheelFilename) -> Iterable[PlatformSpecifics]:
    """
    Extract platform specific information from the given wheel.
    """
    for tag in pwf.platform_tags:
        splitted = tag.split("_", 3)
        if len(splitted) != 4:
            continue
        os, major, minor, arch = splitted
        try:
            parsedArch = KnownArchitecture(arch)
        except ValueError:
            continue
        yield PlatformSpecifics(os, int(major), int(minor), parsedArch)


def wheelNameArchitecture(pwf: ParsedWheelFilename) -> KnownArchitecture:
    """
    Determine the architecture from a wheel.
    """
    if pwf.abi_tags == ["none"] and pwf.platform_tags == ["any"]:
        return KnownArchitecture.purePython
    allSpecifics = list(specifics(pwf))
    if len(allSpecifics) != 1:
        raise ValueError(f"don't know how to handle multi-tag wheels {pwf!r}")
    return allSpecifics[0].architecture


@dataclass
class FusedPair:
    arm64: FilePath[str] | None = None
    x86_64: FilePath[str] | None = None


async def fixArchitectures() -> None:
    """
    Ensure that all wheels installed in the current virtual environment are
    universal2, not x86_64 or arm64.

    This probably only works on an arm64 (i.e., Apple Silicon) machine since it
    requires the ability to run C{pip} under both architectures.
    """
    downloadDir = ".wheels/downloaded"
    tmpDir = ".wheels/tmp"
    fusedDir = ".wheels/fused"

    await c.mkdir("-p", downloadDir, fusedDir, tmpDir)
    for arch in ["arm64", "x86_64"]:
        await c.arch(
            f"-{arch}",
            "pip",
            "wheel",
            "-r",
            "requirements.txt",
            "-w",
            downloadDir,
        )

    needsFusing: defaultdict[str, FusedPair] = defaultdict(FusedPair)

    for child in FilePath(downloadDir).children():
        # every wheel in this list should either be architecture-independent,
        # universal2, *or* have *both* arm64 and x86_64 versions.
        pwf = parse_wheel_filename(child.basename())
        arch = wheelNameArchitecture(pwf)
        if arch in {
            KnownArchitecture.universal2,
            KnownArchitecture.purePython,
        }:
            # This one is fine, no action required.
            continue
        # OK we need to fuse a wheel
        fusor = needsFusing[pwf.project]
        if arch == KnownArchitecture.x86_64:
            fusor.x86_64 = child
        if arch == KnownArchitecture.arm64:
            fusor.arm64 = child

    for name, fusor in needsFusing.items():
        left = fusor.arm64
        if left is None:
            raise RuntimeError(f"no amd64 architecture for {name}")
        right = fusor.x86_64
        if right is None:
            raise RuntimeError(f"no x86_64 architecture for {name}")
        await c["delocate-fuse"](
            "--verbose", f"--wheel-dir={tmpDir}", left.path, right.path
        )
        moveFrom = FilePath(tmpDir).child(left.basename())
        # TODO: properly rewrite / unparse structure
        moveTo = FilePath(fusedDir).child(
            left.basename().replace("_arm64.whl", "_universal2.whl")
        )
        moveFrom.moveTo(moveTo)

    await c.pip(
        "install",
        "--force",
        *[each.path for each in FilePath(fusedDir).globChildren("*.whl")],
    )


start = Deferred.fromCoroutine


async def validateArchitectures(path: FilePath) -> None:
    """
    Ensure that there are no single-architecture binaries in a given directory.
    """
    await c.arch(
        "-arm64",
        "pip",
        "wheel",
        "-r",
        "requirements.txt",
        "-w",
        ".wheels/downloaded",
    )
    await c.arch(
        "-x86_64",
        "pip",
        "wheel",
        "-r",
        "requirements.txt",
        "-w",
        ".wheels/downloaded",
    )


async def signOneFile(
    fileToSign: FilePath, codesigningIdentity: str, entitlements: FilePath
) -> None:
    """
    Code sign a single file.
    """
    fileStr = fileToSign.asTextMode().path
    entitlementsStr = fileToSign.asTextMode().path
    await c.codesign(
        "--sign",
        codesigningIdentity,
        "--entitlements",
        entitlementsStr,
        "--deep",
        "--force",
        "--options",
        "runtime",
    )


T = TypeVar("T")
R = TypeVar("R")


async def createZipFile(zipFile: FilePath, directoryToZip: FilePath) -> None:
    zipPath = zipFile.asTextMode().path
    dirPath = directoryToZip.asTextMode().path
    await c.zip("zip", "-yr", zipPath, dirPath)


def signablePathsIn(topPath: FilePath[str]) -> Iterable[FilePath[str]]:
    """
    What files need to be individually code-signed within a given bundle?
    """
    for p in topPath.walk():
        if p.isfile() and p.splitext()[-1] in {"so", "dylib"}:
            yield p


async def parallel(
    work: Iterable[Coroutine[Deferred[T], T, R]], parallelism: int = 10
) -> AsyncIterable[R]:
    """
    Perform the given work with a limited level of parallelism.
    """
    sem = DeferredSemaphore(parallelism)
    values: Deque[R] = deque()

    async def saveAndRelease(coro: Awaitable[R]) -> None:
        try:
            values.append(await coro)
        finally:
            sem.release()

    async def drain() -> AsyncIterable[R]:
        await sem.acquire()
        while values:
            yield values.popleft()

    for w in work:
        async for each in drain():
            yield each
        start(saveAndRelease(w))

    for x in range(parallelism):
        async for each in drain():
            yield each


@dataclass
class AppBuilder:
    """
    A builder for a particular application
    """

    name: str
    version: str
    notarizeProfile: str
    appleID: str
    teamID: str
    identityHash: str
    entitlementsPath: FilePath[str]

    async def releaseWorkflow(self) -> None:
        """
        Execute the release end to end; build, sign, archive, notarize, staple.
        """
        await self.build()
        await self.signApp()
        await self.archiveApp("signed")
        await self.notarizeApp()
        await self.archiveApp("notarized")

    def archivePath(self, variant: str) -> FilePath[str]:
        """
        The path where we should archive our zip file.
        """
        return FilePath("dist").child(f"{self.name}.{variant}.app.zip")

    async def archiveApp(self, variant: str) -> None:
        """ """
        await createZipFile(self.archivePath(variant), self.originalAppPath())

    async def build(self) -> None:
        """
        Just run py2app.
        """
        await c.python("setup.py", "py2app")

    async def authenticateForSigning(self) -> None:
        """
        Prompt the user to authenticate for code-signing and notarization.
        """
        await c.xcrun(
            "notarytool",
            "store-credentials",
            self.notarizeProfile,
            "--apple-id",
            self.appleID,
            "--team-id",
            self.teamID,
        )

    def originalAppPath(self) -> FilePath[str]:
        """
        A L{FilePath} pointing at the application (prior to notarization).
        """
        return FilePath("./dist").child(self.name + ".app")

    async def signApp(self) -> None:
        """
        Find all binary files which need to be signed within the bundle and run
        C{codesign} to sign them.
        """
        top = self.originalAppPath()
        async for signResult in parallel(
            (
                signOneFile(p, self.identityHash, self.entitlementsPath)
                for p in signablePathsIn(top)
            )
        ):
            print("signed", signResult)
        await signOneFile(top, self.identityHash, self.entitlementsPath)

    async def notarizeApp(self) -> None:
        """
        Submit the built application to Apple for notarization and wait until we
        have seen a response.
        """
        await c.xcrun(
            "notarytool",
            "submit",
            self.archivePath("signed").path,
            f"--apple-id={self.appleID}",
            f"--team-id={self.teamID}",
            f"--keychain-profile={self.notarizeProfile}",
            f"--wait",
        )
        await c.xcrun(
            "xcrun", "stapler", "staple", self.originalAppPath().path
        )


