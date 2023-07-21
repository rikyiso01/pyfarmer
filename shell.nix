{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    python38
    python310
    poetry
    git
  ];

  shellHook = ''
    if [ -z $DOCS ]
    then
      poetry env use python3.8
    else
      poetry env use python3.10
    fi
    poetry install
    git submodule init
    git submodule update
  '';
}
