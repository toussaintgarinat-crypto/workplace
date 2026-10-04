#!/bin/bash
# S237 exercise: create a blank Debian 13 VM on the Proxmox host (never touches other VMs)
# and write a private inventory whose expected machine-id comes from the hypervisor.
# Usage: create_vm.sh <vmid> <private-dir>   (PROXMOX=root@host overrides the hypervisor)
set -euo pipefail
VMID=$1; PRIV=$2; PROXMOX=${PROXMOX:-root@192.168.1.222}
IMAGE_DIR=/mnt/pve/KINGSTON1TO/s237
[[ $VMID =~ ^1[0-9][0-9]$ && $VMID != 103 && $VMID != 104 ]] || { echo "refused vmid"; exit 2; }
ssh -o BatchMode=yes "$PROXMOX" "set -e; qm status $VMID >/dev/null 2>&1 && { echo 'vm exists'; exit 3; }
cd $IMAGE_DIR && grep -E ' debian-13-genericcloud-amd64.qcow2\$' SHA512SUMS | sha512sum -c - >/dev/null
qm create $VMID --name s237-rehearsal-$VMID --memory 12288 --cores 4 --cpu x86-64-v2-AES --ostype l26 --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0,firewall=1 --serial0 socket --vga serial0 --agent 0 --onboot 0 --description 'S237 reconstruction isolee - jetable'
qm set $VMID --scsi0 KINGSTON1TO:0,import-from=$IMAGE_DIR/debian-13-genericcloud-amd64.qcow2,iothread=1,ssd=1,format=qcow2 >/dev/null
qm resize $VMID scsi0 200G
qm set $VMID --ide2 KINGSTON1TO:cloudinit --boot order=scsi0 --ciuser debian --sshkeys $IMAGE_DIR/s237.pub --ipconfig0 ip=dhcp >/dev/null
qm start $VMID"
MAC=$(ssh -o BatchMode=yes "$PROXMOX" "qm config $VMID" | sed -n 's/^net0: virtio=\([^,]*\),.*/\1/p' | tr 'A-F' 'a-f')
UUID=$(ssh -o BatchMode=yes "$PROXMOX" "qm config $VMID" | sed -n 's/^smbios1: uuid=//p' | tr -d '-' | tr 'A-F' 'a-f')
IP=""
for i in $(seq 1 90); do
  for n in $(seq 2 254); do ping -c1 -t1 192.168.1.$n >/dev/null 2>&1 & done; wait
  IP=$(arp -an | grep -i " at ${MAC} " | grep -oE '192\.168\.1\.[0-9]+' | head -1 || true)
  [ -n "$IP" ] && nc -z -G 2 "$IP" 22 2>/dev/null && break
  sleep 3
done
[ -n "$IP" ] || { echo "no address"; exit 4; }
ssh-keygen -R "$IP" >/dev/null 2>&1 || true   # a recycled DHCP address belongs to a new host
for i in $(seq 1 60); do ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 debian@"$IP" true 2>/dev/null && break; sleep 3; done
umask 077
cat > "$PRIV/inventory-$VMID.yml" <<INV
all:
  children:
    rehearsal:
      hosts:
        s237-vm$VMID:
          ansible_host: $IP
          ansible_user: debian
          s237_expected_machine_id: $UUID
INV
echo "vm=$VMID ip=$IP"
