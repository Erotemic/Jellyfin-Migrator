import ubelt as ub
from jellyfin_migrator.demo.oci_container import OCIContainer, OCIContainerEngineConfig
from jellyfin_migrator.demo.demo_media import grab_demo_media
from jellyfin_migrator.demo.jellyfin_init import configure_initial_server
from jellyfin_migrator.demo.jellyfin_init import add_demo_media_libraries


def main():
    paths = grab_demo_media()
    media_dpath = paths['media']
    port = 8098
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
    self = OCIContainer(image='ubuntu:22.04', engine=engine)
    self.start()

    text = ub.codeblock(
        '''
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
        ''')

    fpath = ub.Path.appdir('jellyfin/demo').ensuredir() / 'setup_apt_server.sh'
    fpath.write_text(text)
    self.copy_into(fpath, ub.Path(fpath.name))
    self.call(['bash', 'setup_apt_server.sh'])

    ub.cmd(f'docker exec --detach {self.name} /usr/bin/jellyfin --webdir=/usr/share/jellyfin/web --ffmpeg=/usr/lib/jellyfin-ffmpeg/ffmpeg', verbose=3)
    configure_initial_server(port)
    add_demo_media_libraries(port)


if __name__ == '__main__':
    """
    CommandLine:
        python ~/code/Jellyfin-Migrator/jellyfin_migrator/demo/jellyfin_apt_variant.py
    """
    main()
