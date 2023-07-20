{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    python38
    poetry
    git
  ];

  shellHook = ''
    poetry env use python3.8
    poetry install
    git submodule init
    git submodule update
  '';
}
