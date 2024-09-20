# import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import configure_initial_server


def ensure_docker_variant():
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
    self = OCIContainer(image='jellyfin/jellyfin',
                        name='jellyfin_demo_docker_variant',
                        engine=engine)
    if self.running():
        self.connect()
    elif self.exists():
        self.start()
        self.connect()
    else:
        self.setup()
        import time
        # Query the container until it is ready
        while not self.status() == 'running':
            time.sleep(0.1)
        configure_initial_server(port)
    return self


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/jellyfin_docker_variant.py
    """
    ensure_docker_variant()
