import ubelt as ub


def grab_demo_media(media_dpath=None):
    """
    Example:
        >>> from jellyfin_migrator.demo.demo_media import *  # NOQA
        >>> paths = grab_demo_media()
        >>> print(f'paths = {ub.urepr(paths, nl=1)}')

    """
    if media_dpath is None:
        test_dpath = ub.Path.appdir('jellyfin-migrator/demo-media')
        media_dpath = (test_dpath / 'media')
    media_dpath.ensuredir()
    movies_dpath = (media_dpath / 'movies').ensuredir()
    music_dpath = (media_dpath / 'music').ensuredir()
    shows_dpath = (media_dpath / 'shows').ensuredir()

    movies = [
        {
            'url': 'https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00068306/00068306.mp4',
            'fname': 'Popeye the Sailor meets Sinbad the Sailor.mp4',
            'dpath': movies_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'b90bd60412ba47ad4631dbecbc1215d81506509f394bc81493bfc3085ce64c6f',
        },
        {
            'url': 'https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00000765/00000765.mp4',
            'fname': 'The great train robbery.mp4',
            'dpath': movies_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'fd9ad5affe38208ac8afa1cd311a109ba86daa200aaef75a9485a2b06ee032d9',
        },
    ]

    long_ranger_season1_dpath = (shows_dpath / 'The Lone Ranger' /  'Season 1').ensuredir()
    beverly_hillbillies_season1 = (shows_dpath / 'The Beverly Hillbillies' /  'Season 1').ensuredir()
    beverly_hillbillies_season2 = (shows_dpath / 'The Beverly Hillbillies' /  'Season 2').ensuredir()
    shows = [
        {
            'url': 'https://archive.org/download/theloneranger_201705/s01e01_EntertheLoneRanger.mp4',
            'hash_prefix': 'db1e8a2d3a16c7a314bb8ac9d18466ffb0e78e8c08b0b6cbb85b1bdb0581ea31',
            'hasher': 'sha256',
            'dpath': long_ranger_season1_dpath,
        },
        {
            'url': 'https://archive.org/download/theloneranger_201705/s01e13_finderskeepers.mp4',
            'hash_prefix': '23d23b2d0be6e361ae9144af4b29dd4ac89cd1fa3d52abfb68a858d8c3424ed9',
            'hasher': 'sha256',
            'dpath': long_ranger_season1_dpath,
        },
        {
            'url': 'https://archive.org/download/TheBeverlyHillbillies/The%20Beverly%20Hillbillies/Season%201/The%20Beverly%20Hillbillies%20-%20S01E01%20-%20The%20Clampetts%20Strike%20Oil.mp4',
            'hash_prefix': '917f1059069f2e887ce257e94d320304b1eb6a3b3c7d6556acae64a8947ace26',
            'hasher': 'sha256',
            'dpath': beverly_hillbillies_season1,
        },
        {
            'url': 'https://archive.org/download/TheBeverlyHillbillies/The%20Beverly%20Hillbillies/Season%201/The%20Beverly%20Hillbillies%20-%20S01E36%20-%20Jethro%27s%20Friend.mp4',
            'hash_prefix': 'e1220f344fe9b3ef18ba2b8114d569c86fb02e0f22c76e4eec6d22da41746f7f',
            'hasher': 'sha256',
            'dpath': beverly_hillbillies_season1,
        },
        {
            'url': 'https://archive.org/download/TheBeverlyHillbillies/The%20Beverly%20Hillbillies/Season%202/The%20Beverly%20Hillbillies%20-%20S02E01%20-%20Jed%20Gets%20the%20Misery.mp4',
            'hash_prefix': '7b9851c5de3de7fb074e63295567a6f4205e9756d515f0f0765446d2d6ca25ae',
            'hasher': 'sha256',
            'dpath': beverly_hillbillies_season2,
        },
        {
            'url': 'https://archive.org/download/TheBeverlyHillbillies/The%20Beverly%20Hillbillies/Season%202/The%20Beverly%20Hillbillies%20-%20S02E02%20-%20Hair-Raising%20Holiday.mp4',
            'hash_prefix': '5d60e91c648ed153cbd6a044c4ad279aecce1ea95cb4823977fe3f36ffc671d5',
            'hasher': 'sha256',
            'dpath': beverly_hillbillies_season2,
        },
    ]

    music = [
        {
            'url': 'https://commons.wikimedia.org/wiki/File:Zur%C3%BCck_in_die_Zukunft_(Film)_01.ogg',
            'fname': 'Zurück in die Zukunft.ogg',
            'dpath': music_dpath,
            'hasher': 'sha256',
            'hash_prefix': '37e121978b6f745d91200b1f2cbf48c5b98eac57ac32847397462a2a11526c3b',
        },
        {
            'url': 'https://upload.wikimedia.org/wikipedia/commons/e/e1/Heart_Monitor_Beep--freesound.org.mp3',
            'dpath': music_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'e6a07efeee00b6ce997f12eae505fc74f2726354af8de0c8eabef5ec3f82b083',
        },
        {
            'url': 'https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3',
            'dpath': music_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'f177f9809840b06315c641aca4225fbc48d1fe0e9912232365fd687c2a24dda7',
        },
        {
            'url': 'https://upload.wikimedia.org/wikipedia/commons/7/73/Schoenberg_-_Drei_Klavierst%C3%BCcke_No._1_-_Irakly_Avaliani.webm',
            'dpath': music_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'b87f4a8d5449f5c3953fa5fecf8e2427d089cf3507aa48b22dab8da567b8e529',
        },
        {
            'url': 'https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3',
            'dpath': music_dpath,
            'hasher': 'sha256',
            'hash_prefix': 'f177f9809840b06315c641aca4225fbc48d1fe0e9912232365fd687c2a24dda7',
        },
    ]

    for row in movies:
        ub.grabdata(**row)

    for row in music:
        ub.grabdata(**row)

    for row in shows:
        ub.grabdata(**row)

    collection_paths = {
        'media': media_dpath,
        'movies': movies_dpath,
        'music': music_dpath,
        'shows': shows_dpath,
    }
    return collection_paths
