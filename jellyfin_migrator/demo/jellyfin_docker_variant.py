# import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import configure_initial_server


def main():
    paths = grab_demo_media()
    media_dpath = paths['media']
    port = 8097
    engine = OCIContainerEngineConfig(
        "docker",
        disable_host_mount=True,
        create_args=(
            '--publish',
            f'{port}:8096/tcp',
            '--mount',
            f'type=bind,source={media_dpath},target=/media'
        )
    )
    self = OCIContainer(image='jellyfin/jellyfin', engine=engine)
    self.start()
    configure_initial_server(port)
