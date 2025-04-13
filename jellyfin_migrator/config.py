"""
Defines a flexible configuration so the migrator can be used without modifying
its source code.

This is a rework of the original hard-coded Python-based config.  This defines
a scriptconfig object, which contains all of the necesssary information, has
sensible defaults, and can be modified via the command line or using an
external YAML config file.

Then this file translates the JellyfinMigratorConfig into the data structures
similar to those used by the original migrator logic (which we want to reuse so
we don't have to write this entire thing from scratch).
"""
from pathlib import Path
import os
import scriptconfig as scfg
import ubelt as ub
import kwutil


# These variants are defined for convinience, they illustrate common source
# or destination jellyfin directory structures. Keys defined here can be used
# as shorthand values in the migration section to quickly configure the
# source, target, and original locations of the jellyfin database to migrate.

# Reference:
# https://jellyfin.org/docs/general/administration/configuration/
VARIANTS_YAML = ub.codeblock('''
    windows:
      config:     C:/ProgramData/Jellyfin/Server/config
      cache:      C:/ProgramData/Jellyfin/Server/cache
      log:        C:/ProgramData/Jellyfin/Server/log
      data:       C:/ProgramData/Jellyfin/Server
      transcodes: C:/ProgramData/Jellyfin/Server/transcodes
      ffmpeg:     C:/Program Files/Jellyfin/Server/ffmpeg.exe

    docker:
      config:     /config/config
      cache:      /config/cache
      log:        /config/log
      data:       /config
      transcodes: /config/data/transcodes
      ffmpeg:     /usr/lib/jellyfin-ffmpeg/ffmpeg

    root-apt:
      config:     /root/.config/jellyfin
      cache:      /root/.cache/jellyfin
      log:        /root/.local/share/jellyfin/log
      data:       /root/.local/share/jellyfin
      transcodes: /root/.cache/jellyfin/transcodes
      ffmpeg:     /usr/lib/jellyfin-ffmpeg/ffmpeg

    system-apt:
      config:     /etc/jellyfin/
      cache:      /var/cache/jellyfin
      log:        /var/log/jellyfin
      data:       /var/lib/jellyfin
      transcodes: /var/lib/jellyfin/transcodes
      ffmpeg:     /usr/lib/jellyfin-ffmpeg/ffmpeg
''')


class JellyfinMigratorConfig(scfg.DataConfig):
    """
    The Jellyfin Migrator

    Given a mapping of database and media directories, this will copy relevant
    files into a staging directory, which can then be moved to the final target
    location.
    """

    __epilog__ = '\n'.join([
        ub.codeblock("""
        The predefined shorthand variants are:

        .. code:: yaml
        """),
        ub.indent(VARIANTS_YAML)
    ])

    staging_root = scfg.Value('/staging', help=ub.paragraph(
        '''
        THIS IS WHERE DATA WILL BE WRITTEN TO
        The staging root is the place where the migrator will write all of the
        new data. It is the user's responsibility to move these to the final
        location.
        '''))

    target_path_slash = scfg.Value("/", help=ub.paragraph(
        r'''
        Slash style to use in the target paths (e.g., "\\" for Windows).
        '''))

    log_no_warnings = scfg.Value(False, help=ub.paragraph(
        '''
        Just keep this as false.
        '''))

    log_file = scfg.Value("./jf-migrator.log", help=ub.paragraph(
        '''
        path to where the log file is written
        '''))

    source = scfg.Value('root-apt', help=ub.paragraph(
        '''
        THIS IS WHERE DATA WILL BE READ FROM.
        The source destination is the location where the jellyfin database
        files currently exist. These files will be read from, but never written
        to. This can be a string for a known registered path variant, or it can
        be an explicit YAML dictionary.

        See predefined variants for main options.
        '''))

    target = scfg.Value('docker', help=ub.paragraph(
        '''
        This is the final location where the we want to migrate the jellyfin
        database to.  This tool will not copy the files here, it will only use
        this path to compute relevant hashes, such that when the usere does
        copy the database here, it will work.

        See predefined variants for main options.
        '''
    ))

    original = scfg.Value(None, help=ub.paragraph(
        '''
        If this is unspecified, then we assume source and original are the
        same.  Otherwise, we allow for the uncommon case that the user copied a
        backup of the database to a different location

        See predefined variants for main options.
        '''
    ))

    thread_logs = scfg.Value(True, help='if False, emit logs in serial. Useful for debugging, but slower')

    debug_path = scfg.Value(None, help='directory for debug info')

    # TODO: we could probably infer a reasonable default for this by reading
    # where the media libraries are in the original location, and then assuming
    # they will go into similar locations in the destination.
    media_replacements = scfg.Value(None, help=ub.paragraph(
        '''
        A YAML list of original to target locations for paths used by media
        libraries. Each item is a dict with keys src, and dst. Can also be a
        mapping where the keys are original locations and values are target
        locations, but this is less flexible.

        Currently this must be explicitly specified. We may be able to
        infer reasonable defaults in the future.
        '''))


def postprocess_config(config):
    variants = kwutil.Yaml.loads(VARIANTS_YAML, backend='pyyaml')
    if config['original'] is None:
        config['original'] = config['source']
    if isinstance(config['source'], str):
        config['source'] = variants[config['source']]
    if isinstance(config['target'], str):
        config['target'] = variants[config['target']]
    if isinstance(config['original'], str):
        config['original'] = variants[config['original']]

    if config['media_replacements'] is None:
        config['media_replacements'] = []
    if isinstance(config['media_replacements'], dict):
        new_media_replacements = []
        for src, dst in config['media_replacements'].items():
            new_media_replacements.append({'src': src, 'dst': dst})
        config['media_replacements'] = new_media_replacements
    return config


def prepare_migration_datastructures(config):
    _S = config['source']
    _O = config['original']
    _D = config['target']

    PATH_REPLACEMENTS = {
        # Self-explanatory, I guess. "\\" if migrating *to* Windows, "/" else.
        "target_path_slash": config.target_path_slash,
        # Paths to your libraries
        # "/media/tvshows": "/media/tvshows",
        # "/media/movies": "/media/movies",
        # "/media/music": "/media/music",

        # HACKED IN
        # "/data/jellyfin/media": "/media",
        # "/root/.local/share/jellyfin": "/media",

        # Paths to the different parts of the jellyfin database. Determine these
        # by comparing your existing installation with the paths in your new
        # installation.

        # Setup the path replacemets based on the variant being ported.
        _S['config']: _D['config'],
        _S['cache']: _D['cache'],
        _S['log']: _D['log'],
        _S['data']: _D['data'],
        _S['transcodes']: _D['transcodes'],
        _S['ffmpeg']: _D['ffmpeg'],

        "%MetadataPath%": "%MetadataPath%",
        "%AppDataPath%": "%AppDataPath%",
    }

    for item in config.media_replacements:
        if item['src'] in PATH_REPLACEMENTS:
            raise Exception('Cannot handle case where media replacement src duplicates a known key')
        PATH_REPLACEMENTS[item['src']] = item['dst']

    # This additional replacement dict is required to convert from the paths docker
    # shows to jellyfin back to the actual file system paths to figure out where
    # the files shall be copied. If relative paths are provided, the replacements
    # are done relative to target_root.
    #
    # Even if you're not using docker or not using path mapping with docker,
    # you probably do need to add some entries for accessing the media files
    # and appdata/metadata files. This is because the script must read all the
    # file creation and modification dates *as seen by jellyfin*.
    # In that case and if you're sure that this list is 100% correct,
    # *and only then* you can set "log_no_warnings" to True. Otherwise your logs
    # will be flooded with warnings that it couldn't find an entry to modify the
    # paths (which in that case would be fine because no modifications are needed).
    #
    # If you actually don't need any of this (f.ex. running the script in the
    # same environment as jellyfin), remove all entries except for
    #   * "log_no_warnings" (again, can be set to true if you're sure)
    #   * "target_path_slash"
    #   * %AppDataPath%
    #   * %MetadataPath%.
    FS_PATH_REPLACEMENTS = {
        "log_no_warnings": False,
        "target_path_slash": config.target_path_slash,

        # HACKED IN
        # '/data/jellyfin/media': '/media',
        # '/media': '/data/jellyfin/media',

        # '/config': '/root/.local/share/jellyfin',
        # "/config": "/",
        _D['data']: _S['data'],

        # FIXME: should this be _O instead of _S?
        "%AppDataPath%": os.fspath(Path(_S['data']) / 'data'),
        "%MetadataPath%": os.fspath(Path(_S['data']) / 'metadata'),
        # "/data/tvshows": "Y:/Serien",
        # "/data/movies": "Y:/Filme",
        # "/data/music": "Y:/Musik",
    }

    for item in config.media_replacements:
        if item['dst'] in FS_PATH_REPLACEMENTS:
            raise Exception('Cannot handle case where media replacement dst duplicates a known key')
        FS_PATH_REPLACEMENTS[item['dst']] = item['src']

    STAGING_ROOT = Path(config.staging_root)

    # These generalize the notions of SOURCE_ROOT, TARGET_ROOT, and ORIGINAL_ROOT
    # in the original version of Migrator.
    class ORIGINAL:
        config = Path(_O['config'])
        cache = Path(_O['cache'])
        log = Path(_O['log'])
        data = Path(_O['data'])
        transcodes = Path(_O['transcodes'])
        ffmpeg = Path(_O['ffmpeg'])

    class SOURCE:
        config = Path(_S['config'])
        cache = Path(_S['cache'])
        log = Path(_S['log'])
        data = Path(_S['data'])
        transcodes = Path(_S['transcodes'])
        ffmpeg = Path(_S['ffmpeg'])

    class TARGET:
        config = Path(_D['config'])
        cache = Path(_D['cache'])
        log = Path(_D['log'])
        data = Path(_D['data'])
        transcodes = Path(_D['transcodes'])
        ffmpeg = Path(_D['ffmpeg'])

    class STAGING:
        config = STAGING_ROOT / 'config'
        data = STAGING_ROOT

    ### The To-Do Lists: TODO_LIST_PATHS, TODO_LIST_ID_PATHS and TODO_LIST_IDS.
    # If your installation is like mine, you don't need to change the following three todo_lists.
    # They contain which files should be modified and how.
    # The migration is a multistep process:
    #   1. Specified files are copied to the new location according to the path changes listed above
    #   2. All paths within those files are updated to match the new location
    #   3. The IDs that are used internally and are derived from the paths are updated
    #      1. They occur in jellyfins file paths, so these paths are updated both on the disk and in the databases.
    #      2. All remaining occurences of any IDs are updated throughout all files.
    #   4. Now that all files are where and how they should be, update the file creation and modification
    #      dates in the database.
    # TODO_LIST_PATHS is used for step 1 and 2
    # TODO_LIST_ID_PATHS is used for step 3.1
    # TODO_LIST_IDS is used for step 3.2
    # table and columns for step 4 are hardcoded / determined automatically.
    #
    # General Notes:
    #   * For step 1, "path_replacements" is used to determine the new file paths.
    #   * In step 2, the "replacements" from the todo_list is used, but it makes no sense to set it
    #     to something different from what you used in step 1.
    #   * In step 3 the "replacements" entry in the todo_lists is auto-generated, no need to touch it either.
    #
    # Notes from my own jellyfin installation:
    #   3.1 seems to be "ancestor-str" and "ancestor" formatted IDs only (see jellyfin_id_scanner for details on the format)
    #   3.2 seems like only certain .db files contain them.
    #   Search for "ID types occurring in paths" to find the place in the code
    #   where you can select the types to include.

    # New: only the database files first.
    TODO_LIST_PATHS_1 = [
        {
            "source": SOURCE.data / "data/library.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",                      # Usually you want to leave this on auto. If you want to work on the source file, set it to the same path (YOU SHOULDN'T!).
            "replacements": PATH_REPLACEMENTS,     # Usually same for all but you could specify a specific one per db.
            "tables": {
                "TypedBaseItems": {        # Name of the table within the SQLite database file
                    "path_columns": [      # All column names that can contain paths.
                        "path",
                    ],
                    "jf_image_columns": [  # All column names that can jellyfins "image paths mixed with image properties" strings.
                        "Images",
                    ],
                    "json_columns": [      # All column names that can contain json data with paths.
                        "data",
                    ],
                },
                "mediastreams": {
                    "path_columns": [
                        "Path",
                    ],
                },
                "Chapters2": {
                    "jf_image_columns": [
                        "ImagePath",
                    ],
                },
            },
        },
        {
            "source": SOURCE.data / "data/jellyfin.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
            "tables": {
                "ImageInfos": {
                    "path_columns": [
                        "Path",
                    ],
                },
            },
        },
        # Copy all other .db files. Since it's copy-only (no path adjustments), omit the log output.
        {
            "source": SOURCE.data / "data/*.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
            "copy_only": True,
            "no_log": False,
        },
    ]

    TODO_LIST_PATHS_2 = [
        {
            "source": SOURCE.data / "plugins/**/*.json",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        {
            "source": SOURCE.config / "*.xml",
            "source_root": SOURCE.config,
            "original_root": ORIGINAL.config,
            "target_root": TARGET.config,
            "staging_root": STAGING.config,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        {
            "source": SOURCE.data / "metadata/**/*.nfo",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        {
            # .xml, .mblink, .collection files are here.
            "source": SOURCE.data / "root/**/*.*",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        {
            "source": SOURCE.data / "data/collections/**/collection.xml",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        {
            "source": SOURCE.data / "data/playlists/**/playlist.xml",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
        },

        # Lastly, copy anything that's left. Any file that's already been processed/copied is skipped
        # ... you should delete the cache and the logs though.
        {
            "source": SOURCE.data / "**/*.*",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto",
            "replacements": PATH_REPLACEMENTS,
            "copy_only": True,
            "no_log": False,
        },
    ]

    # See comment from TODO_LIST_PATHS for details about this todo_list.
    # "replacements" designates the source -> target path replacement dict.
    # Same as for the matching job in TODO_LIST_PATHS.
    # The ID replacements are determined automatically.
    TODO_LIST_ID_PATHS = [
        {
            "source": SOURCE.data / "data/library.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
            "tables": {
                "TypedBaseItems": {        # Name of the table within the SQLite database file
                    "path_columns": [      # All column names that can contain paths.
                        "path",
                    ],
                    "jf_image_columns": [  # All column names that can jellyfins "image paths mixed with image properties" strings.
                        "Images",
                    ],
                    "json_columns": [      # All column names that can contain json data with paths OR IDs!!
                        "data",
                    ],
                },
                "mediastreams": {
                    "path_columns": [
                        "Path",
                    ],
                },
                "Chapters2": {
                    "jf_image_columns": [
                        "ImagePath",
                    ],
                },
            },
        },

        {
            "source": SOURCE.config / "*.xml",
            "source_root": SOURCE.config,
            "original_root": ORIGINAL.config,
            "target_root": TARGET.config,
            "staging_root": STAGING.config,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
        },

        {
            "source": SOURCE.data / "metadata/**/*",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
        },

        {
            # .xml, .mblink, .collection files are here.
            "source": SOURCE.data / "root/**/*",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
        },

        {
            "source": SOURCE.data / "data/**/*",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
        },
    ]

    # See comment from TODO_LIST_PATHS for details about this todo_list.
    # "replacements" designates the source -> target path replacement dict.
    # The ID replacements are determined automatically.
    TODO_LIST_IDS = [
        {
            "source": SOURCE.data / "data/library.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
            "tables": {
                "AncestorIds": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [
                        "AncestorIdText",
                    ],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                        "AncestorId",
                    ],
                },
                "Chapters2": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                    ],
                },
                "ItemValues": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                    ],
                },
                "People": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                    ],
                },
                "TypedBaseItems": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [
                        "TopParentId",
                        "PresentationUniqueKey",
                        "SeriesPresentationUniqueKey",
                    ],
                    "ancestor-str-dash": [
                        "UserDataKey",
                        "ExtraIds",
                    ],
                    "bin": [
                        "guid",
                        "ParentId",
                        "SeasonId",
                        "SeriesId",
                        "OwnerId"
                    ],
                },
                "UserDatas": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [
                        "key",
                    ],
                    "bin": [],
                },
                "mediaattachments": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                    ],
                },
                "mediastreams": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [],
                    "ancestor-str-dash": [],
                    "bin": [
                        "ItemId",
                    ],
                },
            },
        },
        {
            "source": SOURCE.data / "data/playback_reporting.db",
            "source_root": SOURCE.data,
            "original_root": ORIGINAL.data,
            "target_root": TARGET.data,
            "staging_root": STAGING.data,
            "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
            "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
            "tables": {
                "PlaybackActivity": {
                    "str": [],
                    "str-dash": [],
                    "ancestor-str": [
                        "ItemId",
                    ],
                    "ancestor-str-dash": [],
                    "bin": [],
                },
            },
        },
    ]

    migration_datastructures = {
        'PATH_REPLACEMENTS': PATH_REPLACEMENTS,
        'FS_PATH_REPLACEMENTS': FS_PATH_REPLACEMENTS,
        'TODO_LIST_PATHS_1': TODO_LIST_PATHS_1,
        'TODO_LIST_PATHS_2': TODO_LIST_PATHS_2,
        'TODO_LIST_ID_PATHS': TODO_LIST_ID_PATHS,
        'TODO_LIST_IDS': TODO_LIST_IDS,
    }
    return migration_datastructures
