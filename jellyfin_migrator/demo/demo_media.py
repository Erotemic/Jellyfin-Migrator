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
    ub.grabdata('https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00068306/00068306.mp4', fname='Popeye the Sailor meets Sinbad the Sailor.mp4', dpath=movies_dpath)
    ub.grabdata('https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00000765/00000765.mp4', fname='The great train robbery.mp4', dpath=movies_dpath)

    ub.grabdata('https://commons.wikimedia.org/wiki/File:Zur%C3%BCck_in_die_Zukunft_(Film)_01.ogg', fname='Zurück in die Zukunft.ogg', dpath=music_dpath)
    ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/e/e1/Heart_Monitor_Beep--freesound.org.mp3', dpath=music_dpath)
    ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3', dpath=music_dpath)
    ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/7/73/Schoenberg_-_Drei_Klavierst%C3%BCcke_No._1_-_Irakly_Avaliani.webm', dpath=music_dpath)
    ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3', dpath=music_dpath)
    collection_paths = {
        'media': media_dpath,
        'movies': movies_dpath,
        'music': music_dpath,
    }
    return collection_paths
