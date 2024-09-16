"""
CommandLine:
    xdoctest -m jellyfin_migrator.demo.oci_container __doc__:0
    xdoctest ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/oci_container.py  __doc__:0

Example:
    >>> import sys, ubelt
    >>> sys.path.append(ubelt.expandpath('~/code/Jellyfin-Migrator'))
    >>> from jellyfin_migrator.demo.oci_container import *  # NOQA
    >>> from jellyfin_migrator.demo.oci_container import _check_engine_version
    >>> image1 = 'jellyfin/jellyfin'
    >>> image2 = 'ubuntu:22.04'
    >>> for image in [image1, image2]:
    >>>     self = OCIContainer(image=image)
    >>>     with self:
    >>>         self.call(["echo", "hello world"])
    >>>         self.call(["cat", "/proc/1/cgroup"])
    >>>         #print(self.get_environment())
    >>>         #print(self.debug_info())

"""
import io
import json
import os
import shlex
import subprocess
import sys
import typing
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath, PurePosixPath
from types import TracebackType
from typing import IO, Dict, Literal, Any
from typing import Union

from packaging.version import InvalidVersion, Version
import ubelt as ub

if typing.TYPE_CHECKING:
    PopenBytes = subprocess.Popen[bytes]
    PathOrStr = Union[str, os.PathLike[str]]
else:
    PopenBytes = subprocess.Popen
    PathOrStr = Union[str, "os.PathLike[str]"]

ContainerEngineName = Literal["docker", "podman"]
IS_WIN: bool = sys.platform.startswith("win")


class OCIEngineTooOldError(BaseException):
    return_code = 7


# Order of the enum matters for tests. 386 shall appear before amd64.
class OCIPlatform(Enum):
    i386 = "linux/386"
    AMD64 = "linux/amd64"
    ARM64 = "linux/arm64"
    PPC64LE = "linux/ppc64le"
    S390X = "linux/s390x"

# TODO: get this platform
import platform  # NOQA
print(platform.machine())
if platform.machine() == 'x86_64':
    DEFAULT_PLATFORM = OCIPlatform.AMD64
else:
    raise NotImplementedError


@dataclass(frozen=True)
class OCIContainerEngineConfig:
    name: ContainerEngineName
    create_args: tuple[str, ...] = field(default_factory=tuple)
    disable_host_mount: bool = False

    @staticmethod
    def from_config_string(config_string: str):
        name = 'docker'
        name = typing.cast(ContainerEngineName, name)
        # some flexibility in the option names to cope with TOML conventions
        create_args = []
        disable_host_mount = False

        return OCIContainerEngineConfig(
            name=name, create_args=tuple(create_args), disable_host_mount=disable_host_mount
        )

    def options_summary(self) -> str | dict[str, str]:
        if not self.create_args:
            return self.name
        else:
            return {
                "name": self.name,
                "create_args": repr(self.create_args),
                "disable_host_mount": str(self.disable_host_mount),
            }


DEFAULT_ENGINE = OCIContainerEngineConfig("docker")


def _check_engine_version(engine: OCIContainerEngineConfig) -> None:
    try:
        version_string = call(engine.name, "version", "-f", "{{json .}}", capture_stdout=True)
        version_info = json.loads(version_string.strip())
        if engine.name == "docker":
            # --platform support was introduced in 1.32 as experimental
            # docker cp, as used by cibuildwheel, has been fixed in v24 => API 1.43, https://github.com/moby/moby/issues/38995
            client_api_version = Version(version_info["Client"]["ApiVersion"])
            engine_api_version = Version(version_info["Server"]["ApiVersion"])
            version_supported = min(client_api_version, engine_api_version) >= Version("1.43")
        elif engine.name == "podman":
            client_api_version = Version(version_info["Client"]["APIVersion"])
            if "Server" in version_info:
                engine_api_version = Version(version_info["Server"]["APIVersion"])
            else:
                engine_api_version = client_api_version
            # --platform support was introduced in v3
            version_supported = min(client_api_version, engine_api_version) >= Version("3")

        if not version_supported:
            raise OCIEngineTooOldError() from None
    except (subprocess.CalledProcessError, KeyError, InvalidVersion) as e:
        raise OCIEngineTooOldError() from e


class OCIContainer:
    """
    An object that represents a running OCI (e.g. Docker) container.

    Intended for use as a context manager e.g.
    `with OCIContainer(image = 'ubuntu') as docker:`

    A bash shell is running in the remote container. When `call()` is invoked,
    the command is relayed to the remote shell, and the results are streamed
    back to cibuildwheel.
    """

    UTILITY_PYTHON = "/opt/python/cp38-cp38/bin/python"

    process: PopenBytes
    bash_stdin: IO[bytes]
    bash_stdout: IO[bytes]

    def __init__(
        self,
        *,
        image: str,
        oci_platform: OCIPlatform = DEFAULT_PLATFORM,
        cwd: PathOrStr | None = None,
        engine: OCIContainerEngineConfig = DEFAULT_ENGINE,
        appname: str = 'demo_container',
    ):
        if not image:
            msg = "Must have a non-empty image to run."
            raise ValueError(msg)

        self.image = image
        self.oci_platform = oci_platform
        self.cwd = cwd
        self.name: str | None = None
        self.engine = engine
        self.appname = appname

    def _get_platform_args(self, *, oci_platform: OCIPlatform | None = None) -> tuple[str, str]:
        if oci_platform is None:
            oci_platform = self.oci_platform

        # we need '--pull=always' otherwise some images with the wrong platform get re-used (e.g. 386 image for amd64)
        # c.f. https://github.com/moby/moby/issues/48197#issuecomment-2282802313
        pull = "always"
        try:
            image_platform = call(
                self.engine.name,
                "image",
                "inspect",
                self.image,
                "--format",
                "{{.Os}}/{{.Architecture}}",
                capture_stdout=True,
            ).strip()
            if image_platform == oci_platform.value:
                # in case the correct image is already present, don't pull
                # this allows to run local only images
                pull = "never"
        except subprocess.CalledProcessError:
            pass
        return f"--platform={oci_platform.value}", f"--pull={pull}"

    def __enter__(self):
        return self.start()

    def start(self):
        self.name = f"{self.appname}-{uuid.uuid4()}"

        _check_engine_version(self.engine)

        # work-around for Travis-CI PPC64le Docker runs since 2021:
        # this avoids network splits
        # https://github.com/pypa/cibuildwheel/issues/904
        # https://github.com/conda-forge/conda-smithy/pull/1520
        network_args = []

        platform_args = self._get_platform_args()

        simulate_32_bit = False
        if self.oci_platform == OCIPlatform.i386:
            # If the architecture running the image is already the right one
            # or the image entrypoint takes care of enforcing this, then we don't need to
            # simulate this
            run_cmd = [self.engine.name, "run", "--rm"]
            ctr_cmd = ["uname", "-m"]
            try:
                container_machine = call(
                    *run_cmd, *platform_args, self.image, *ctr_cmd, capture_stdout=True
                ).strip()
            except subprocess.CalledProcessError:
                # The image might have been built with amd64 architecture
                # Let's try that
                platform_args = self._get_platform_args(oci_platform=OCIPlatform.AMD64)
                container_machine = call(
                    *run_cmd, *platform_args, self.image, *ctr_cmd, capture_stdout=True
                ).strip()
            simulate_32_bit = container_machine != "i686"

        shell_args = ["linux32", "/bin/bash"] if simulate_32_bit else ["/bin/bash"]

        # subprocess.run
        ub.cmd(
            [
                self.engine.name,
                "create",
                # "--env=CIBUILDWHEEL",
                # "--env=SOURCE_DATE_EPOCH",
                f"--name={self.name}",
                # *['--entrypoint', '/bin/sh -c'],
                "--interactive",
                *(["--volume=/:/host"] if not self.engine.disable_host_mount else []),
                *network_args,
                *platform_args,
                *self.engine.create_args,
                self.image,
                *shell_args,
            ],
            check=True,
            verbose=3
        )

        print('About to start process')
        # self.process = subprocess.Popen(
        #     [
        #         self.engine.name,
        #         "start",
        #         "--attach",
        #         "--interactive",
        #         self.name,
        #     ],
        #     stdin=subprocess.PIPE,
        #     stdout=subprocess.PIPE,
        # )
        ub.cmd(
            [
                self.engine.name,
                "start",
                # "--attach",
                # "--interactive",
                self.name,
            ],
            # stdin=subprocess.PIPE,
            # stdout=subprocess.PIPE,
            verbose=3)

        print('Make process to comunicate with container')
        self.process = subprocess.Popen(
            [
                self.engine.name,
                "exec",
                # "-it",
                # "--attach",
                "--interactive",
                self.name,
                "bin/bash",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        print('Finished creating process')

        assert self.process.stdin
        assert self.process.stdout
        self.bash_stdin = self.process.stdin
        self.bash_stdout = self.process.stdout

        print('Calling true')
        # run a noop command to block until the container is responding
        self.call(["/bin/true"], cwd="/")
        print('Called true')

        if self.cwd:
            # Although `docker create -w` does create the working dir if it
            # does not exist, podman does not. There does not seem to be a way
            # to setup a workdir for a container running in podman.
            self.call(["mkdir", "-p", os.fspath(self.cwd)], cwd="/")
        print('Return self')

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()

    def stop(self):
        self.bash_stdin.write(b"exit 0\n")
        self.bash_stdin.flush()
        self.process.wait(timeout=30)
        self.bash_stdin.close()
        self.bash_stdout.close()

        if self.engine.name == "podman":
            # This works around what seems to be a race condition in the podman
            # backend. The full reason is not understood. See PR #966 for a
            # discussion on possible causes and attempts to remove this line.
            # For now, this seems to work "well enough".
            self.process.wait()

        assert isinstance(self.name, str)

        if 0:
            # Could do a graceful stop, but it is not needed
            ub.cmd(
                [self.engine.name, "stop", self.name],
                # stdout=subprocess.DEVNULL,
                check=False,
                verbose=3,
            )

        keep_container = 0
        if not keep_container:
            # subprocess.run(
            ub.cmd(
                [self.engine.name, "rm", "--force", "-v", self.name],
                # stdout=subprocess.DEVNULL,
                check=False,
                verbose=3,
            )
            self.name = None

    def copy_into(self, from_path: Path, to_path: PurePath) -> None:
        if from_path.is_dir():
            self.call(["mkdir", "-p", to_path])
            call(self.engine.name, "cp", f"{from_path}/.", f"{self.name}:{to_path}")
        else:
            self.call(["mkdir", "-p", to_path.parent])
            call(self.engine.name, "cp", from_path, f"{self.name}:{to_path}")

    def copy_out(self, from_path: PurePath, to_path: Path) -> None:
        # note: we assume from_path is a dir
        to_path.mkdir(parents=True, exist_ok=True)
        call(self.engine.name, "cp", f"{self.name}:{from_path}/.", to_path)

    def glob(self, path: PurePosixPath, pattern: str) -> list[PurePosixPath]:
        glob_pattern = path.joinpath(pattern)

        path_strings = json.loads(
            self.call(
                [
                    self.UTILITY_PYTHON,
                    "-c",
                    f"import sys, json, glob; json.dump(glob.glob({str(glob_pattern)!r}), sys.stdout)",
                ],
                capture_output=True,
            )
        )

        return [PurePosixPath(p) for p in path_strings]

    def call(
        self,
        args: Sequence[PathOrStr],
        env: Mapping[str, str] | None = None,
        capture_output: bool = False,
        cwd: PathOrStr | None = None,
    ) -> str:
        if cwd is None:
            # Podman does not start the a container in a specific working dir
            # so we always need to specify it when making calls.
            cwd = self.cwd

        chdir = f"cd {cwd}" if cwd else ""
        env_assignments = (
            " ".join(f"{shlex.quote(k)}={shlex.quote(v)}" for k, v in env.items())
            if env is not None
            else ""
        )
        command = " ".join(shlex.quote(str(a)) for a in args)
        end_of_message = str(uuid.uuid4())

        # log the command we're executing
        print(f"    + {command}")

        # Write a command to the remote shell. First we change the
        # cwd, if that's required. Then, we use the `env` utility to run
        # `command` inside the specified environment. We use `env` because it
        # can cope with spaces and strange characters in the name or value.
        # Finally, the remote shell is told to write a footer - this will show
        # up in the output so we know when to stop reading, and will include
        # the return code of `command`.
        self.bash_stdin.write(
            bytes(
                f"""(
            {chdir}
            env {env_assignments} {command}
            printf "%04d%s\n" $? {end_of_message}
        )
        """,
                encoding="utf8",
                errors="surrogateescape",
            )
        )
        self.bash_stdin.flush()

        if capture_output:
            output_io: IO[bytes] = io.BytesIO()
        else:
            output_io = sys.stdout.buffer

        while True:
            line = self.bash_stdout.readline()

            if line.endswith(bytes(end_of_message, encoding="utf8") + b"\n"):
                # fmt: off
                footer_offset = (
                    len(line)
                    - 1  # newline character
                    - len(end_of_message)  # delimiter
                    - 4  # 4 return code decimals
                )
                # fmt: on
                return_code_str = line[footer_offset : footer_offset + 4]
                return_code = int(return_code_str)
                # add the last line to output, without the footer
                output_io.write(line[0:footer_offset])
                output_io.flush()
                break
            else:
                output_io.write(line)
                output_io.flush()

        if isinstance(output_io, io.BytesIO):
            output = str(output_io.getvalue(), encoding="utf8", errors="surrogateescape")
        else:
            output = ""

        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, args, output)

        return output

    def get_environment(self) -> dict[str, str]:
        env = json.loads(
            self.call(
                [
                    self.UTILITY_PYTHON,
                    "-c",
                    "import sys, json, os; json.dump(os.environ.copy(), sys.stdout)",
                ],
                capture_output=True,
            )
        )
        return typing.cast(Dict[str, str], env)

    def environment_executor(self, command: Sequence[str], environment: dict[str, str]) -> str:
        # used as an EnvironmentExecutor to evaluate commands and capture output
        return self.call(command, env=environment, capture_output=True)

    def debug_info(self) -> str:
        if self.engine.name == "podman":
            command = f"{self.engine.name} info --debug"
        else:
            command = f"{self.engine.name} info"
        # completed = subprocess.run(
        completed = ub.cmd(
            command,
            shell=True,
            check=True,
            cwd=self.cwd,
            # stdin=subprocess.PIPE,
            # stdout=subprocess.PIPE,
            verbose=3,
            # universal_newlines=False,
        )
        output = completed.stdout
        # output = str(completed.stdout, encoding="utf8", errors="surrogateescape")
        return output


def shell_quote(path: PurePath) -> str:
    return shlex.quote(os.fspath(path))


def call(
    *args: PathOrStr,
    env: Mapping[str, str] | None = None,
    cwd: PathOrStr | None = None,
    capture_stdout: bool = False,
) -> str | None:
    """
    Run subprocess.run, but print the commands first. Takes the commands as
    *args. Uses shell=True on Windows due to a bug. Also converts to
    Paths to strings, due to Windows behavior at least on older Pythons.
    https://bugs.python.org/issue8557
    """
    args_ = [str(arg) for arg in args]
    # print the command executing for the logs
    print("+ " + " ".join(shlex.quote(a) for a in args_))
    kwargs: dict[str, Any] = {}
    if capture_stdout:
        kwargs["universal_newlines"] = True
        kwargs["stdout"] = subprocess.PIPE
    result = subprocess.run(args_, check=True, shell=IS_WIN, env=env, cwd=cwd, **kwargs)
    # result = ub.cmd(args_, check=True, shell=IS_WIN, env=env, cwd=cwd, verbose=3, **kwargs)
    if not capture_stdout:
        return None
    return typing.cast(str, result.stdout)
