# S246 — VM 100 « dokploy » : journal d'installation (sans secret)

## Task 1 (2026-11-25)
- Méthode : image cloud Debian 13 (voie b, celle de `infra/ansible/exercise/create_vm.sh`), SHA512 vérifié.
- Choix non destructif : la définition de la VM 100 est conservée ; l'ISO est retirée, l'ancien disque
  vide (32 Go) reste détaché en `unused0` (`vm-100-disk-0.qcow2`), nouveau disque 60 Go importé.
- RAM 5824 Mo, 2 cœurs, démarrage auto au boot de l'hyperviseur (`onboot 1`), cloud-init `debian` + clé du Mac.
- IP LAN (DHCP) : 192.168.1.165 (à réserver côté routeur ou fixer avant d'exposer des services).
- Vérifié : Debian 13 (trixie), ~5,6 Go RAM, 59 Go disque, SSH par clé OK. RAM libre nœud avant démarrage : 8,4 Go.
