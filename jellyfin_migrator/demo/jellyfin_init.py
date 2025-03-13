from jellyfin_apiclient_python import JellyfinClient


def is_server_alive(port, verbose=1):
    r"""
    Check if the local jellyfin server is alive on a port

    Ignore:
        curl -X GET "http://localhost:8098/Startup/User" \
          -H "Content-Type: application/json" \
          -d '{"Name": "jellyfin", "Password": "jellyfin"}' \
                --show-error --fail

        curl -X GET "http://localhost:8098/Startup/User" --show-error --fail
        curl -X GET "http://localhost:8098" --show-error --fail
        curl -X GET "http://localhost:8098/web/#/home.html" --show-error --fail -i
        curl -X GET "http://localhost:8098" --show-error --fail -i
    """
    url = 'http://localhost'
    import requests
    try:
        resp = requests.get(f'{url}:{port}/Startup/User')
        # json={"Name": "jellyfin", "Password": "jellyfin"})
    except Exception as ex:
        ex
        if verbose:
            print(f'ex={ex}')
            print('waiting')
    else:
        if verbose:
            print(f'resp={resp}')
        if resp.ok:
            return True
    return False


def is_server_alive2(port):
    client = JellyfinClient()
    url = 'http://localhost'
    client.config.app(
        name='AliveChecker',
        version='0.1.0',
        device_name='machine_name',
        device_id='unique_id')
    client.config.data["auth.ssl"] = True
    url = f'{url}:{port}'
    username = 'jellyfin'
    password = 'jellyfin'
    try:
        client.auth.connect_to_address(url)
        client.auth.login(url, username, password)
        client.jellyfin.users()
    except Exception:
        return False
    else:
        return True


def configure_initial_server(port):
    """
    Send post commands that will initialize the server
    """
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


def add_demo_media_libraries(port, media_dpath='/media'):
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
        paths=[str(media_dpath) + '/movies'], refreshLibrary=True,
    )
    client.jellyfin.add_media_library(
        name='Music', collectionType='music',
        paths=[str(media_dpath) + '/music'], refreshLibrary=True,
    )
