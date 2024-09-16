import ubelt as ub
from jellyfin_apiclient_python import JellyfinClient
import time
import requests

# Ensure we have the jellyfin container image.
oci_exe = 'docker'
image_name = 'ubuntu'
container_name = 'jellyfin_apt'
ub.cmd(f'{oci_exe} pull {image_name}', check=True, verbose=3)

ub.cmd(f'{oci_exe} stop {container_name}', verbose=3)

# Ensure the media path that we are mounting exists
port = 8098

test_dpath = ub.Path.appdir('jellyfin-migrator/demo/demo_server_apt')
media_dpath = (test_dpath / 'media').ensuredir()
media_dpath.ensuredir()


test_dpath = ub.Path.appdir('jellyfin-migrator/demo/demo_server_apt')
media_dpath = (test_dpath / 'media').ensuredir()
media_dpath.ensuredir()
movies_dpath = (media_dpath / 'movies').ensuredir()
music_dpath = (media_dpath / 'music').ensuredir()

# TODO: fix bbb
# zip_fpath = ub.grabdata('https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_normal.mp4.zip',
#                         dpath=movies_dpath,
#                         hash_prefix='e320fef389ec749117d0c1583945039266a40f25483881c2ff0d33207e62b362',
#                         hasher='sha256')
# mp4_fpath = ub.Path(zip_fpath).augment(ext='')
# if not mp4_fpath.exists():
#     import zipfile
#     zfile = zipfile.ZipFile(zip_fpath)
#     zfile.extractall(path=media_dpath)

ub.grabdata('https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00068306/00068306.mp4', fname='Popeye the Sailor meets Sinbad the Sailor.mp4', dpath=movies_dpath)
ub.grabdata('https://tile.loc.gov/storage-services/service/mbrs/ntscrm/00000765/00000765.mp4', fname='The great train robbery.mp4', dpath=movies_dpath)

ub.grabdata('https://commons.wikimedia.org/wiki/File:Zur%C3%BCck_in_die_Zukunft_(Film)_01.ogg', fname='Zurück in die Zukunft.ogg', dpath=music_dpath)
ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/e/e1/Heart_Monitor_Beep--freesound.org.mp3', dpath=music_dpath)
ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3', dpath=music_dpath)
ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/7/73/Schoenberg_-_Drei_Klavierst%C3%BCcke_No._1_-_Irakly_Avaliani.webm', dpath=music_dpath)
ub.grabdata('https://upload.wikimedia.org/wikipedia/commons/6/63/Clair_de_Lune_-_Wright_Brass_-_United_States_Air_Force_Band_of_Flight.mp3', dpath=music_dpath)

docker_args = [
    'docker', 'run',
    '--rm=true',
    '--detach=true',
    '--name', container_name,
    '--publish', f'{port}:8096/tcp',
    '--entrypoint', '/bin/sh',
    '--mount', f'type=bind,source={media_dpath},target=/media',
    '--restart', 'no',
    '-it',
    image_name,
]
ub.cmd(docker_args, verbose=3, check=True)

# Wait for the server to spin up.
info = ub.cmd(f'{oci_exe} ps', verbose=3)
while 'starting' in info.stdout:
    time.sleep(3)
    info = ub.cmd(f'{oci_exe} ps', verbose=3)


#ub.codeblock
text = '''
#!/usr/bin/env bash
export DEBIAN_FRONTEND=noninteractive
apt update
apt-get install software-properties-common -y
apt install curl gnupg -y
add-apt-repository universe

mkdir -p /etc/apt/keyrings
curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg

cat <<EOF | tee /etc/apt/sources.list.d/jellyfin.sources
Types: deb
URIs: https://repo.jellyfin.org/$( awk -F'=' '/^ID=/{ print $NF }' /etc/os-release )
Suites: $( awk -F'=' '/^VERSION_CODENAME=/{ print $NF }' /etc/os-release )
Components: main
Architectures: $( dpkg --print-architecture )
Signed-By: /etc/apt/keyrings/jellyfin.gpg
EOF

apt update
apt install jellyfin -y

# Use this to run jellyfin instead of systemctl
#/usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg

# Does not work because systemctl is not available in the container
# systemctl start jellyfin
# systemctl status jellyfin --no-pager
'''


fpath = ub.Path.appdir('jellyfin/demo').ensuredir() / 'setup_apt_server.sh'
fpath.write_text(text)
ub.cmd(f'docker cp {fpath} {container_name}:setup_apt_server.sh', verbose=3)
ub.cmd(f'docker exec {container_name} chmod +x setup_apt_server.sh', verbose=3)
ub.cmd(f'docker exec {container_name} bash setup_apt_server.sh', verbose=3)
ub.cmd(f'docker exec --detach {container_name} /usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg', verbose=3)

"""
docker exec -it jellyfin_apt /bin/bash
docker stop jellyfin_apt
"""


# Programatically initialize the new server with a user with name
# "jellyfin" and password "jellyfin". This process was discovered
# by looking at what the webUI does, and isn't part of the core
# jellyfin API, so it may break in the future.

# References:
# https://matrix.to/#/!YOoxJKhsHoXZiIHyBG:matrix.org/$H4ymY6TE0mtkVEaaxQDNosjLN7xXE__U_gy3u-FGPas?via=bonifacelabs.ca&via=t2bot.io&via=matrix.org
time.sleep(10)

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

# Create a client to perform some initial configuration.
client = JellyfinClient()
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
