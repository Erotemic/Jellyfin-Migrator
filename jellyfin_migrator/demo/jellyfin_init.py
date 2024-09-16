from jellyfin_apiclient_python import JellyfinClient


def configure_initial_server(port):
    import requests
    import time
    # time.sleep(10)

    url = 'http://localhost'
    resp = requests.post(f'{url}:{port}/Startup/Configuration', json={"UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"})
    assert resp.ok
    time.sleep(1)

    resp = requests.get(f'{url}:{port}/Startup/User')
    assert resp.ok
    time.sleep(1)

    resp = requests.post(f'{url}:{port}/Startup/User', json={"Name": "jellyfin", "Password": "jellyfin"})
    assert resp.ok
    time.sleep(1)

    payload = {"UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"}
    resp = requests.post(f'{url}:{port}/Startup/Configuration', json=payload)
    assert resp.ok
    time.sleep(1)

    payload = {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False}
    resp = requests.post(f'{url}:{port}/Startup/RemoteAccess', json=payload)
    assert resp.ok
    time.sleep(1)

    resp = requests.post(f'{url}:{port}/Startup/Complete')
    assert resp.ok
    time.sleep(1)


def add_demo_media_libraries(port):
    # Create a client to perform some initial configuration.
    client = JellyfinClient()
    url = 'http://localhost'
    client.config.app(
        name='DemoServerMediaPopulator',
        version='0.1.0',
        device_name='machine_name',
        device_id='unique_id')
    client.config.data["auth.ssl"] = True
    url = f'{url}:{port}'
    username = 'jellyfin'
    password = 'jellyfin'
    client.auth.connect_to_address(url)
    client.auth.login(url, username, password)

    client.jellyfin.add_media_library(
        name='Movies', collectionType='movies',
        paths=['/media/movies'], refreshLibrary=True,
    )
    client.jellyfin.add_media_library(
        name='Music', collectionType='music',
        paths=['/media/music'], refreshLibrary=True,
    )
