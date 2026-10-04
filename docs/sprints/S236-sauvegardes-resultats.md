# S236 — Preuves et état de livraison

Date : 2026-10-04. **Terminé pour les sauvegardes et la restauration applicative isolée.** Sauvegarde USB chiffrée, restauration éprouvée et planification systemd active. RPO retenu : 24 h ; RTO visé : 8 h. La reconstruction d’un nouvel hôte reste à éprouver dans S237.

## Sauvegardes en service

Destination choisie : clé USB PHILIPS, partition exFAT UUID `6A01-B378`, montée sur `/mnt/workplace-backup`. Elle est rattachée à chaud à la VM 103 sur Proxmox Yourown ; montage persistant par UUID, sans formatage ni suppression des fichiers existants. Les profils acceptent aussi disque externe, NAS monté et serveur local/distant via SFTP, S3 ou WebDAV HTTPS ; seule la destination USB est éprouvée ici.

L’inventaire couvre 76 conteneurs, dont 71 actifs et cinq sidecars déjà arrêtés : 45 ensembles de fichiers/SQLite, six serveurs PostgreSQL, Qdrant et etcd, soit 53 sources. Les fichiers utilisateur, le dépôt applicatif, les configurations montées et les environnements Docker privés sont inclus. Les producteurs sont suspendus pendant les exports natifs, puis repris par identité avec journal durable. Une génération partielle n’est jamais publiée.

Duplicati stable 2.4.0.0 épinglé transporte les générations complètes avec chiffrement AES et vérification complète avant acquittement ; rétention USB de 30 versions. Le staging et les rapports contenant des données restent privés, hors Git. La phrase AES et les profils sont aussi conservés sur le Mac dans `~/Documents/Workplace-Recovery/`, dossier 0700 et fichiers 0600. Correspondance de la phrase vérifiée sans affichage.

Premier job systemd réel réussi : génération `20261004T115244Z-148a3bc4`, 53 sources, export et transfert vérifiés, `Result=success`, `ExecMainStatus=0`, aucun journal de reprise restant. Les 71 services sont tous sains et le Cœur répond HTTP 200 après reprise.

`workplace-backup.timer` est **enabled/active** : 00h00 et 12h00, heure locale Europe/Paris, avec décalage aléatoire maximal de 15 min et rattrapage après arrêt. Prochain passage observé à l’activation : 2026-10-05 00:08:45 CEST. La clé doit rester disponible pour tenir la cadence.

## Restauration réellement éprouvée

La génération post-réparation `20261003T194537Z-4b4fddd5` a été récupérée depuis la clé avec une base Duplicati vierge en **10,44 s**. Les 53 sources, empreintes et manifeste original concordent ; aucune dépendance à la base Duplicati initiale.

Répétition complète sur cible neuve `application-rehearsal-20261004-fresh5` : **493,64 s (8 min 13,64 s)**, dont 114,49 s de restauration native. Avec la récupération USB mesurée séparément, ces étapes représentent environ **8 min 24 s**.

- Les 45 ensembles de fichiers/SQLite sont restaurés et contrôlés ; les six serveurs PostgreSQL retrouvent toutes leurs bases, rôles, extensions et comptages, sans omission d’index.
- Qdrant retrouve sa collection et une recherche sur un vecteur réel ; etcd est sain.
- Sessions réelles des Keycloak restaurés : dashboard Cœur authentifié 200, accès sans session 303 ; CRUD Données complet avec JWT signé ; Oria authentifié 200 ; lecture authentifiée de deux résultats Mémoire.
- Gateway retrouve 57 modèles et réalise un appel via sa véritable authentification, base et routage vers un fournisseur OpenAI factice local. Aucun appel payant ni inférence de modèle n’est attesté.
- Les 57 services de base sont sains au contrôle final. Onze services supplémentaires démarrent, deviennent réellement sains puis sont arrêtés par phases : frontend Oria, Forge backend, Connexion, ClamAV, voix, écoute, Grafana, IDE, SearxNG, Kuma et PeerTube.
- Nettoyage confirmé : zéro conteneur, volume ou réseau S236 restant, copies de données supprimées, aucun échec de nettoyage.

Les cibles utilisent exclusivement leurs copies, des réseaux internes sans route hôte et aucun port publié/socket Docker de production. Des plafonds mémoire et une réserve de 3 Gio protègent la production. Le polling du frontend Oria et le dimensionnement mémoire sont adaptés uniquement dans le laboratoire.

## Corrections et contrôles

La première restauration stricte a révélé un index unique Gateway incohérent : 21 groupes de noms dupliqués. Après essai isolé et dump privé, une transaction conserve les 367 enregistrements et tous leurs IDs/champs, archive les 42 originaux dans `s236_recovery.gateway_tool_original`, renomme les 21 inscriptions secondaires et recrée l’index unique. Le redump et la génération suivante se restaurent strictement. Cette réparation spécifique n’est pas exécutée automatiquement par le restaurateur.

Le test réel de clé absente refuse le job avant toute suspension ; les identités de production restent inchangées. Montage rétabli immédiatement, sans modification des fichiers utilisateur. Le RPO utilise le début de la génération effectivement transférée, et non l’heure de transfert. Après le premier job systemd, Prometheus reçoit `workplace_backup_rpo_ok=1`, transfert réussi et zéro source en échec. Les 13 règles Prometheus ont été validées ; aucun nouveau canal externe de notification n’est ajouté.

**85 tests automatisés passent**, ainsi que la compilation, la syntaxe de l’installateur et le contrôle du diff. Code et deltas de sécurité revus sans blocage.

## Limites de la preuve

L’exercice valide les données et les parcours applicatifs représentatifs sur le HP, avec ses images disponibles et des démarrages par phases. Il ne prouve ni fonctionnement simultané de tout le stack, ni reconstruction d’un nouvel hôte, ni haute disponibilité Patroni, ni inférence ou connecteurs externes. Le RTO global après perte du HP demeure à éprouver dans S237. L’historique Prometheus et les caches explicitement reproductibles sont exclus ; leurs configurations utiles sont couvertes.

Les preuves privées sont conservées sous `/home/debian/s236-tools/application-rehearsal-20261004-fresh5/` et `/home/debian/.local/share/workplace-backups/`. Guides : [sauvegardes cohérentes](../../outils/sauvegarde/coherent/README.md), [Duplicati](../../outils/sauvegarde/duplicati/README.md), [planification USB](../../outils/sauvegarde/duplicati/USB-SCHEDULE.md), [conception](../superpowers/specs/2026-10-03-S236-sauvegardes-coherentes-design.md).
