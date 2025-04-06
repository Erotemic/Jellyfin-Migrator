from string import ascii_letters
import datetime
import hashlib
import pathlib
from pathlib import Path


try:
    from line_profiler import profile
except ImportError:
    from ubelt import identity as profile


def get_dotnet_MD5(s: str):
    """
    Note: The .NET .Unicode method encodes as UTF16 little endian:
    https://docs.microsoft.com/en-us/dotnet/api/system.text.encoding.unicode?view=net-6.0
    """
    return hashlib.md5(s.encode("utf-16-le")).digest()


@profile
def nested_id_path_replacer(d, to_replace: dict):
    """
    Almost the same as nested_root_path_replacer but for replacing id parts somewhere in
    the paths including file names (can't use "is_relative_to" for checking).
    ID paths usually have the format '.../83/833addde992893e93d0572907f8b4cad/...'. It's
    important to note and change that parent folder with the firs byte of the id, too.
    Sometimes the parent folder is just single digit. This code handles any subsring that
    starts at the beginning of the id string.
    """
    modified, ignored = 0, 0
    warnings = []
    if isinstance(d, dict):
        for k, v in d.items():
            d[k], mo, ig, wrns = nested_id_path_replacer(v, to_replace)
            modified += mo
            ignored  += ig
            warnings += wrns
    elif isinstance(d, list):
        for i, e in enumerate(d):
            d[i], mo, ig, wrns = nested_id_path_replacer(e, to_replace)
            modified += mo
            ignored  += ig
            warnings += wrns
    elif isinstance(d, str) or isinstance(d, pathlib.PurePath):
        try:
            p = Path(d)
        except Exception:
            # This actually doesn't occur I think; Path() can pretty much convert any string into a Path
            # object (which is equivalent to saying it doesn't have any restrictions for filenames).
            ignored += 1
        else:
            found = False

            src, dst = "", ""

            if set(p.stem).issubset(set("0123456789abcdef-")):
                dst = to_replace.get(p.stem, "")
                if dst:
                    found = True
                    p = p.with_stem(dst)

            if not found:
                for part in p.parts[:-1]:
                    # Check if it can actually be an ID. If so, look it up (which is expensive).
                    if set(part).issubset(set("0123456789abcdef-")):
                        src = part
                        dst = to_replace.get(part, "")
                        if dst:
                            break
                if dst:
                    found = True
                    q = Path()
                    # Find folder as path object that needs to be changed
                    q = p
                    while p.name != src:
                        p = p.parent
                    # q becomes the part relative to the now determined p part (with p.stem = id)
                    q = q.relative_to(p)
                    p = p.with_name(dst)

                    # Check if the parent folder starts with byte(s) from the id
                    if src.startswith(p.parent.name):
                        # If so, move the already replaced part from p to q
                        q = p.name / q
                        p = p.parent
                        # Replace required number of bytes
                        p = p.with_name(dst[:len(p.name)])

                    # Merge q and p back together
                    p = p / q
            if found:
                modified += 1
                # I guess 99% of the users won't migrate _to_ windows but the script could generate
                # \ paths anyways.
                # p.as_posix() makes sure that we always get a string with "/". Otherwise, on windows,
                # str(p) would automatically return "\" paths.
                d = p.as_posix().replace("/", to_replace["target_path_slash"])
            else:
                ignored += 1
                # Unlike nested_root_path_replacer, there is no need to warn the user about
                # potential paths that haven't been altered. In case you suspect that something is
                # overlooked, check out ./id_scanner.py.
                # ignored is purely maintained for signature compatibility with nested_root_path_replacer.
    return d, modified, ignored, warnings


@profile
def jf_date_str_to_python_ns(s: str):
    # Python datetime has only support for microseconds because of resolution
    # problems. To convert from a date+time to ticks, the fractional seconds
    # part doesn't matter anyway (it remains the same). Hence, it's cut off
    # and added back later.
    subseconds = "0"
    if "." in s:
        s, subseconds = s.rsplit(".", 1)
    # In case subseconds has a higher resolution than 100ns and/or additional
    # information (f.ex. timezone, which is known to be UTC+00:00 for jellyfin),
    # Strip all of it.
    # Add trailing zeros til the ns digit, then convert to int, and we have ns.
    subseconds = int(subseconds.split("+")[0].rstrip(ascii_letters).ljust(9, "0"))
    # Add explicit information about the timezone (UTC+00:00)
    s += "+00:00"
    t = int(datetime.datetime.fromisoformat(s).timestamp())
    # Convert to ns
    t *= 1000000000
    t += subseconds
    return t


@profile
def get_datestr_from_python_time_ns(time_ns: int):
    """
    Convert a _python_ timestamp (float seconds since epoch, which is os dependent)
    to a ISO like date string as found in the jellyfin database. I have no idea
    if this works for all OS'es in all timezones. Very likely not but that whole
    topic is about as much of a mess as jellyfin's databases. If you got any issues,
    I'm sorry. If you find a solution, them, please let me know!
    """
    # Datetime has no support for sub-microsecond resolution (which is required here).
    # Doesn't matter anyway, we can add the whole sub-second part afterwards.
    time_s = time_ns // 1000000000
    time_frac_s_100ns = (time_ns // 100) % 10000000
    timestamp = datetime.datetime.utcfromtimestamp(time_s).isoformat(sep=" ", timespec="seconds")
    # Add back the sub-seconds part and the UTC time zone
    timestamp += "." + str(time_frac_s_100ns).rjust(7, "0").rstrip("0") + "Z"
    return timestamp


@profile
def delete_empty_folders(dir: str):
    dir = Path(dir)

    done = False
    while not done:
        done = True
        for p in dir.glob("**"):
            if not list(p.iterdir()):
                p.rmdir()
                done = False


@profile
def _single_file_path_replacer(d, to_replace: dict):
    modified, ignored = 0, 0
    warnings = []
    try:
        p = Path(d)
    except Exception:
        # This actually doesn't occur I think; Path() can pretty much convert any string into a Path
        # object (which is equivalent to saying it doesn't have any restrictions for filenames).
        ignored += 1
    else:
        found = False
        for src, dst in to_replace.items():
            if p.is_relative_to(src):
                # This filters out all the "garbage" paths that actually were no paths to begin with
                # and of course all the paths that are actually not relative to the src, dst couple
                # currently checked.
                p = dst / p.relative_to(src)
                # I guess 99% of the users won't migrate _to_ windows but the script could generate
                # \ paths anyways.
                # p.as_posix() makes sure that we always get a string with "/". Otherwise, on windows,
                # str(p) would automatically return "\" paths.
                d = p.as_posix().replace("/", to_replace["target_path_slash"])
                found = True
                break
        if found:
            modified += 1
        else:
            ignored += 1
            # No need to consider all the Path("sometext") objects. This might not be 100%
            # accurate, but it eliminates 99.9999% of the false-positives. This output is
            # after all only to give you a hint whether you missed a path.
            # Also exclude URLs. Btw: pathlib can be quite handy for messing with URLs.
            if len(p.parents) > 1 \
                    and not str(d).startswith("https:") \
                    and not str(d).startswith("http:") \
                    and not to_replace.get("log_no_warnings", False):
                warnings.append(f"No entry for this (presumed) path: {d}")
                # print_log(f"No entry for this (presumed) path: {d}")
    return d, modified, ignored, warnings


@profile
def nested_root_path_replacer(d, to_replace: dict):
    """
    Recursively replace all paths in "d" which can be
     * a path object
     * a path string
     * a dictionary (only values are checked, no keys).
     * a list
     * any nested structure of the above.
     * anything else is returned unmodified.
    Returns the (un)modified object as well as how many items have been modified or ignored.
    """
    import pathlib
    # TODO: would likely be much faster with IndexableWalker
    modified, ignored = 0, 0
    warnings = []
    if isinstance(d, dict):
        for k, v in d.items():
            d[k], mo, ig, wrn = nested_root_path_replacer(v, to_replace)
            modified += mo
            ignored  += ig
            warnings += wrn
    elif isinstance(d, list):
        for i, e in enumerate(d):
            d[i], mo, ig, wrn = nested_root_path_replacer(e, to_replace)
            modified += mo
            ignored  += ig
            warnings += wrn
    elif isinstance(d, str) or isinstance(d, pathlib.PurePath):
        d, mo, ig, wrn = _single_file_path_replacer(d, to_replace)
        modified += mo
        ignored += ig
        warnings += wrn
    return d, modified, ignored, warnings


@profile
def remove_subpaths(path_list):
    """
    Remove paths that are subdirectories of other paths in the list.

    Args:
        path_list: List of path strings to process

    Returns:
        List of paths with no subpaths remaining
    """
    result = []
    for path in path_list:
        if not any(path.is_relative_to(o) for o in path_list if o != path):
            result.append(path)
    return result


@profile
def requires_permission(config):
    """
    Check if we will need elevated permissions to copy some files.
    """
    from os import access, R_OK, X_OK
    import ubelt as ub
    paths = list(config['source'].values())
    paths = [ub.Path(p) for p in paths]
    paths = remove_subpaths(paths)
    class RequiresPermission(Exception):
        ...
    try:
        import kwutil
        pman = kwutil.ProgressManager()
        with pman:
            for dpath in pman.progiter(paths, desc='prescan paths'):
                for r, ds, fs in dpath.walk():
                    for fname in fs:
                        path = r / fname
                        if not access(path, R_OK):
                            raise RequiresPermission
                    if not access(r, X_OK):
                        raise RequiresPermission
    except RequiresPermission:
        print('Detected that permissions will be required')
        return True
    else:
        print('No eleveated permissions will be required')
        return False


class SudoCredentialRefresher:
    def __init__(self, interval: float = 300.0):
        """
        Initialize the sudo credential refresher.

        Args:
            interval: Refresh interval in seconds (default 300 = 5 minutes)
        """
        import threading
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = None

    def _refresh_loop(self):
        """Background thread that periodically validates sudo credentials"""
        import subprocess
        while not self._stop_event.wait(self.interval):
            try:
                subprocess.run(
                    ['sudo', '--validate'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError:
                # If validation fails, try to re-authenticate
                try:
                    subprocess.run(
                        ['sudo', '--askpass', '--validate'],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except subprocess.CalledProcessError:
                    # If we can't re-authenticate, stop the thread
                    self._stop_event.set()
                    break

    def start(self):
        """Start the background refresh thread"""
        import threading
        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._refresh_loop,
                daemon=True  # Thread will exit when main program exits
            )
            self._thread.start()

    def stop(self):
        """Stop the background refresh thread"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def __enter__(self):
        """Context manager entry"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop()
