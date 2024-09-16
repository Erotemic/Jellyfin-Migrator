from pathlib import Path

# TODO BEFORE YOU START:
# * Create a copy of the jellyfin database you want to migrate
# * Delete the following temp/cache folders (resp. the matching
#   folders for your installation)
#   * C:/ProgramData/Jellyfin/Server/cache
#   * C:/ProgramData/Jellyfin/Server/log
#   * C:/ProgramData/Jellyfin/Server/data/subtitles
#     Note: this only contains *cached* subtitles that have been
#           extracted on-the-fly from files streamed to clients.
#   * RTFM (read the README.md) and you're ready to go.
#   * Careful when replacing everything in your new installation,
#     you might want to *not* copy your old network settings
#     (C:/ProgramData/Jellyfin/Server/config/networking.xml)


# Please specify a log file. The script is rather verbose and important
# errors might get lost in the process. You should definitely check the
# log file after running the script to see if there are any warnings or
# other important messages! Use f.ex. notepad++ (npp) to quickly
# highlight and remove bunches of uninteresting log messages:
#   * Open log file in npp
#   * Go to "Search -> Mark... (CTRL + M)"
#   * Tick "Bookmark Line"
#   * Search for strings that (only!) occur in the lines you want to
#     remove. All those lines should get a marking next to the line number.
#   * Go to "Search -> Bookmark -> Remove Bookmarked Lines"
#   * Repeat as needed
# Text encoding is UTF-8 (in npp selectable under "Encoding -> UTF-8")
LOG_FILE = "D:/jf-migrator.log"


# These paths will be processed in the order they're listed here.
# This can be very important! F.ex. if specific subfolders go to a different
# place than stuff in the root dir of a given path, the subfolders must be
# processed first. Otherwise, they'll be moved to the same place as the other
# stuff in the root folder.
# Note: all the strings below will be converted to Path objects, so it doesn't
# matter whether you write / or \\ or include a trailing / . After the path
# replacement it will be converted back to a string with slashes as specified
# by target_path_slash.
# Note2: The AppDataPath and MetadataPath entries are only there to make sure
# the script recognizes them as actual paths. This is necessary to adjust
# the (back)slashes as specified. This can only be done on "known" paths
# because (back)slashes occur in other strings, too, where they must not be
# changed.
PATH_REPLACEMENTS = {
    # Self-explanatory, I guess. "\\" if migrating *to* Windows, "/" else.
    "target_path_slash": "/",
    # Paths to your libraries
    "D:/Serien": "/data/tvshows",
    "F:/Serien": "/data/tvshows",
    "F:/Filme": "/data/movies",
    "F:/Musik": "/data/music",
    # Paths to the different parts of the jellyfin database. Determine these
    # by comparing your existing installation with the paths in your new
    # installation.
    "C:/ProgramData/Jellyfin/Server/config": "/config",
    "C:/ProgramData/Jellyfin/Server/cache": "/config/cache",
    "C:/ProgramData/Jellyfin/Server/log": "/config/log",
    "C:/ProgramData/Jellyfin/Server": "/config/data",  # everything else: metadata, plugins, ...
    "C:/ProgramData/Jellyfin/Server/transcodes": "/config/data/transcodes",
    "C:/Program Files/Jellyfin/Server/ffmpeg.exe": "usr/lib/jellyfin-ffmpeg/ffmpeg",
    "%MetadataPath%": "%MetadataPath%",
    "%AppDataPath%": "%AppDataPath%",
}


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
    "target_path_slash": "/",
    "/config": "/",
    "%AppDataPath%": "/data/data",
    "%MetadataPath%": "/data/metadata",
    "/data/tvshows": "Y:/Serien",
    "/data/movies": "Y:/Filme",
    "/data/music": "Y:/Musik",
}


# Original root only needs to be filled if you're using auto target paths _and_
# if your source dir doesn't match the source paths specified above in
# path_replacements.
# auto target will first replace SOURCE_ROOT with original_root in a given path
# and then do the replacement according to the path_replacements dict.
# This is required if you copied your jellyfin DB to another location and then
# start processing it with this script.
ORIGINAL_ROOT = Path("C:/ProgramData/Jellyfin/Server")
SOURCE_ROOT = Path("D:/Jellyfin/Server")
TARGET_ROOT = Path("D:/Jellyfin-dummy")


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
TODO_LIST_PATHS = [
    {
        "source": SOURCE_ROOT / "data/library.db",
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
        "source": SOURCE_ROOT / "data/jellyfin.db",
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
        "source": SOURCE_ROOT / "data/*.db",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
        "copy_only": True,
        "no_log": True,
    },

    {
        "source": SOURCE_ROOT / "plugins/**/*.json",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    {
        "source": SOURCE_ROOT / "config/*.xml",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    {
        "source": SOURCE_ROOT / "metadata/**/*.nfo",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    {
        # .xml, .mblink, .collection files are here.
        "source": SOURCE_ROOT / "root/**/*.*",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    {
        "source": SOURCE_ROOT / "data/collections/**/collection.xml",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    {
        "source": SOURCE_ROOT / "data/playlists/**/playlist.xml",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
    },

    # Lastly, copy anything that's left. Any file that's already been processed/copied is skipped
    # ... you should delete the cache and the logs though.
    {
        "source": SOURCE_ROOT / "**/*.*",
        "target": "auto",
        "replacements": PATH_REPLACEMENTS,
        "copy_only": True,
        "no_log": True,
    },
]

# See comment from TODO_LIST_PATHS for details about this todo_list.
# "replacements" designates the source -> target path replacement dict.
# Same as for the matching job in TODO_LIST_PATHS.
# The ID replacements are determined automatically.
TODO_LIST_ID_PATHS = [
    {
        "source": SOURCE_ROOT / "data/library.db",
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
        "source": SOURCE_ROOT / "config/*.xml",
        "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
        "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
    },

    {
        "source": SOURCE_ROOT / "metadata/**/*",
        "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
        "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
    },

    {
        # .xml, .mblink, .collection files are here.
        "source": SOURCE_ROOT / "root/**/*",
        "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
        "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
    },

    {
        "source": SOURCE_ROOT / "data/**/*",
        "target": "auto-existing",             # If you used "auto" in TODO_LIST_PATHS, leave this on "auto-existing". Otherwise specify same path.
        "replacements": {"oldids": "newids"},  # Will be auto-generated during the migration.
    },
]

# See comment from TODO_LIST_PATHS for details about this todo_list.
# "replacements" designates the source -> target path replacement dict.
# The ID replacements are determined automatically.
TODO_LIST_IDS = [
    {
        "source": SOURCE_ROOT / "data/library.db",
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
        "source": SOURCE_ROOT / "data/playback_reporting.db",
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
