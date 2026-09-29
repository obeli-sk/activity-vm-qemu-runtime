{
  description = "Native QEMU activity VM runtime for Obelisk";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e158d9ed9b51c98974c5e66e1ba1c9e0255fecaa";
    trynix.url = "github:fzakaria/trynix/7e7e793594cb58efb48279b17b4e15bbc6fbe91b";
    bochs-runtime.url = "github:obeli-sk/activity-vm-bochs-runtime/d8e3d71965f01b4a2b63b4d84af8d37eecda137f";
  };

  outputs = { nixpkgs, trynix, bochs-runtime, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      trynixPackages = trynix.packages.${system};
      bochsPackages = bochs-runtime.packages.${system};
      # virtio-mem lets Obelisk plug guest RAM after restore, so one snapshot serves every size.
      # VIRTIO_MEM depends on EXCLUSIVE_SYSTEM_RAM, which needs STRICT_DEVMEM. The Bochs kernel
      # is uniprocessor; SMP and ACPI CPU hotplug let Obelisk add vCPUs after restore too.
      kernel = bochsPackages.linux.overrideAttrs (old: {
        postPatch = old.postPatch + ''
          scripts/config --file .config \
            -e MEMORY_HOTPLUG -e MEMORY_HOTPLUG_DEFAULT_ONLINE -e MEMORY_HOTREMOVE \
            -e MHP_MEMMAP_ON_MEMORY -e STRICT_DEVMEM -e VIRTIO_MEM \
            -e SMP --set-val NR_CPUS 64 \
            -e ACPI_CONTAINER -e ACPI_HOTPLUG_CPU
        '';
        postBuild = ''
          grep -qx CONFIG_VIRTIO_MEM=y .config
          grep -qx CONFIG_SMP=y .config
          grep -qx CONFIG_ACPI_HOTPLUG_CPU=y .config
        '';
      });
      settime = pkgs.pkgsStatic.runCommandCC "settime" { } ''
        mkdir -p $out/bin
        $CC -O2 -Wall -Werror -o $out/bin/settime ${./settime.c}
      '';
      runtime = pkgs.runCommand "activity-vm-qemu-tcg-runtime" {
        src = ./.;
        nativeBuildInputs = [ pkgs.bash pkgs.libarchive pkgs.gzip pkgs.python3 ];
      } ''
        bash "$src/build-bundle.sh" \
          ${pkgs.qemu}/bin/qemu-system-x86_64 \
          ${kernel}/bzImage \
          ${bochsPackages.rootfs}/rootfs.bin \
          ${trynixPackages.site}/guest \
          ${settime}/bin/settime \
          "$out" tcg
        python3 "$src/make-snapshot.py" "$out"
      '';
    in {
      packages.${system} = {
        inherit runtime settime;
        qemu-tcg = pkgs.qemu;
        qemu-kvm = pkgs.qemu;
        site = trynixPackages.site;
        inherit kernel;
        rootfs = bochsPackages.rootfs;
        default = runtime;
      };
      checks.${system}.runtime = runtime;
      devShells.${system}.default = pkgs.mkShell {
        packages = [ pkgs.bash pkgs.libarchive pkgs.gzip pkgs.python3 pkgs.jq pkgs.zstd ];
      };
    };
}
