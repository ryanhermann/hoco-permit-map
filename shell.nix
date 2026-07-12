{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.pdfplumber ps.requests ps.pytest ]))
    pkgs.nodejs
  ];
}
