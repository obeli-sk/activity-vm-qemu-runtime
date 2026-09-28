{
  description = "Native QEMU activity VM runtime for Obelisk";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/e158d9ed9b51c98974c5e66e1ba1c9e0255fecaa";
    trynix.url = "github:fzakaria/trynix/7e7e793594cb58efb48279b17b4e15bbc6fbe91b";
    bochs-runtime.url = "github:obeli-sk/activity-vm-bochs-runtime/b4710a4fb7c4dec97315e70323219f83f799d725";
  };

  outputs = { nixpkgs, trynix, bochs-runtime, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      trynixPackages = trynix.packages.${system};
      bochsPackages = bochs-runtime.packages.${system};
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
          ${bochsPackages.linux}/bzImage \
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
        kernel = bochsPackages.linux;
        rootfs = bochsPackages.rootfs;
        default = runtime;
      };
      checks.${system}.runtime = runtime;
      devShells.${system}.default = pkgs.mkShell {
        packages = [ pkgs.bash pkgs.libarchive pkgs.gzip pkgs.python3 pkgs.jq pkgs.zstd ];
      };
    };
}
