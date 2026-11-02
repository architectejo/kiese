# Checklist d'installation desktop — ETS. KIESE

Procédure de test **manuelle, humaine**, à exécuter sur de vraies machines Windows avant tout
déploiement en boulangerie. Ce document ne remplace pas les vérifications automatisées décrites
dans `docs/qa/rapports/testeur-installation-<date>.md` (migrations, sauvegarde, logique Python/TS) :
il couvre tout ce qui ne peut être constaté que sur une machine physique, dans les conditions
réelles du client (pas d'administrateur, antivirus actif, parfois sans Internet).

Référence : `docs/architecture/DESKTOP.md` (toutes sections), CLAUDE.md §8.

**Conditions à réunir avant de commencer** :
- Deux machines de test au minimum : **Windows 10** et **Windows 11**, à jour des mises à jour
  Windows courantes.
- Un compte Windows **non administrateur** (le compte utilisé au quotidien par un gérant/facturier
  n'a généralement pas de droits admin).
- Un antivirus **actif** (Windows Defender suffit s'il n'y en a pas d'autre ; ne pas le désactiver
  pour les tests — c'est justement le scénario réel).
- Un scénario **sans connexion Internet** disponible (coupure Wi-Fi/câble, ou machine isolée) en
  plus d'un scénario avec connexion, pour distinguer les deux.
- Les deux fichiers livrés par `packaging-desktop`/`build-all.ps1` : l'installeur
  `KIESE-Setup-<version>.exe` (et une version `<version N+1>` pour le test de mise à jour).
- Un jeton de nœud valide fourni par le siège (menu Nœuds) si le test de connexion au cloud doit
  être couvert ; sinon utiliser « Continuer hors-ligne ».

**Avant de commencer, points déjà connus (registre des bugs)** à garder à l'esprit pendant les
tests, pour ne pas ouvrir de doublon :
- **BUG-074** (Majeur, en cours de correction par `dev-frontend`) : aucun écran frontend
  « Administration → Restaurer une sauvegarde ». L'étape « Restauration de sauvegarde » ci-dessous
  ne pourra donc, tant que ce ticket n'est pas corrigé, être testée que via le filet de sécurité
  (dossier des sauvegardes ouvert automatiquement par le dialogue d'erreur, restauration manuelle
  du fichier `.sqlite3.gz` par un technicien) — documenter ce constat plutôt que cocher KO à tort.
- **BUG-075/BUG-076** (`docs/qa/CHECKLIST_MATERIEL.md`) : l'impression silencieuse desktop n'est
  pas encore atteignable depuis l'interface (bouton « Imprimer » encore câblé sur `window.print()`)
  — ne pas s'étonner si l'étape « Impression » ci-dessous se comporte comme le navigateur plutôt
  que comme une impression silencieuse.
- **BUG-072** (Mineur, ouvert) : usage manuel de `sync_now` seulement — sans impact sur ce document
  (la boucle automatique du poste, elle, est conforme).

Pour chaque étape : **Résultat attendu** / case **OK · KO** / champ **Observation** (version
Windows, modèle de PC, message exact affiché, capture d'écran si pertinent dans `docs/qa/captures/`).

---

## 1. Installation

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 1.1 | Télécharger/copier `KIESE-Setup-<version>.exe` sur le poste, double-clic, sans droits admin | L'assistant NSIS démarre sans demander d'élévation de privilèges (ou, si Windows la demande, l'installation réussit avec les droits du compte standard dans le dossier choisi par l'utilisateur) | | |
| 1.2 | Antivirus actif pendant l'installation | Aucun blocage silencieux ; si l'antivirus affiche une alerte (fréquent avec un exécutable PyInstaller/Electron non signé), elle est compréhensible et contournable sans expertise technique | | |
| 1.3 | Choix du dossier d'installation (`allowToChangeInstallationDirectory: true`) | L'utilisateur peut changer le dossier proposé ; l'installation se termine sans erreur quel que soit le dossier choisi (y compris un chemin avec espace ou accent) | | |
| 1.4 | Raccourcis créés | Icône sur le Bureau **et** dans le menu Démarrer (`createDesktopShortcut: always`, `createStartMenuShortcut: true`) | | |
| 1.5 | Taille et durée | Installeur conforme à l'objectif DESKTOP.md §12 (< 250 Mo) ; installation complète en quelques minutes sur un PC modeste | | |
| 1.6 | Sans connexion Internet | L'installation se termine sans erreur (aucune étape de l'installeur NSIS ne doit nécessiter le réseau) | | |

---

## 2. Premier lancement — assistant de première installation (DESKTOP.md §7)

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 2.1 | Premier double-clic sur l'icône KIESE | Écran de démarrage (`splash.html`) puis l'assistant s'affiche (pas la fenêtre principale) | | |
| 2.2 | Choix de la langue | Français disponible et correctement affiché partout dans la suite de l'assistant | | |
| 2.3 | Code boulangerie | Saisie d'un code existant (K1…B2) acceptée ; code invalide/vide refusé avec message clair | | |
| 2.4 | Connexion au cloud avec jeton valide, Internet disponible | Test de connexion réussi, message de succès | | |
| 2.5 | Connexion au cloud, jeton invalide ou Internet coupé | Message d'erreur clair (pas de blocage de l'assistant) ; le test échoue, suggérant une seconde tentative ou le mode hors-ligne | | |
| 2.6 | « Continuer hors-ligne » | L'assistant continue normalement sans URL ni jeton cloud | | |
| 2.7 | Compte administrateur local de secours | Création acceptée avec un nom d'utilisateur et un mot de passe valides ; refus clair si le mot de passe est trop court/vide | | |
| 2.8 | Choix de l'imprimante | La liste proposée correspond aux imprimantes réellement installées sous Windows (y compris « Microsoft Print to PDF » comme repère neutre si aucune thermique n'est branchée) | | |
| 2.9 | Récapitulatif final | Toutes les informations saisies apparaissent correctement avant validation | | |
| 2.10 | Fin de l'assistant | La fenêtre principale se charge, connexion à l'application possible avec le compte créé à l'étape 2.7 | | |

---

## 3. Connexion et facturation

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 3.1 | Connexion avec le compte administrateur local | Connexion réussie, tableau de bord affiché | | |
| 3.2 | Créer une facture simple (1-2 pains, client existant ou nouveau) | Facture créée sans erreur, BP mis à jour, montants corrects en FC | | |
| 3.3 | Livraison de la facture | Déstockage effectué, statut passé à livré | | |

---

## 4. Impression

**Rappel** : BUG-075/BUG-076 ouverts — documenter le comportement réel plutôt que d'attendre à
tort l'impression silencieuse tant qu'ils ne sont pas corrigés (voir `CHECKLIST_MATERIEL.md` §1.B).

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 4.1 | Impression du reçu de la facture de l'étape 3.2 | Ticket imprimé lisible sur l'imprimante configurée à l'étape 2.8 (ou aperçu PDF si aucune imprimante physique) | | |

---

## 5. Fermeture / réouverture

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 5.1 | Fermer l'application (croix ou Alt+F4) | Arrêt propre : le processus `kiese-server.exe` disparaît du Gestionnaire des tâches dans les 5 s (SIGTERM puis arrêt forcé en dernier recours, `desktop/src/backend.ts::stop`) | | |
| 5.2 | Rouvrir l'application | Redémarrage direct sur la fenêtre principale (pas l'assistant), reconnexion avec le même compte, les données de l'étape 3 sont toujours présentes | | |
| 5.3 | Fermer l'application pendant qu'une facture est en cours de saisie (non enregistrée) | Aucune corruption de données ; au pire, la saisie non enregistrée est perdue (comportement attendu d'un formulaire non soumis), mais les factures déjà enregistrées restent intactes | | |

---

## 6. Mise à jour

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 6.1 | Installer la version N, créer des données (facture, client) | Base `kiese.sqlite3` sous `%APPDATA%\KIESE\` contient ces données | | |
| 6.2 | Mettre à disposition la version N+1 (serveur de mise à jour `electron-updater`, ou installeur N+1 lancé manuellement par-dessus) | La mise à jour est proposée à la fermeture de l'application (pas installée pendant une vacation), conformément à DESKTOP.md §11 | | |
| 6.3 | Accepter l'installation | Fermeture propre, installation, redémarrage automatique en version N+1 | | |
| 6.4 | Vérifier les données après mise à jour | Les données créées en 6.1 sont toujours présentes, aucune perte | | |
| 6.5 | Vérifier la sauvegarde pré-migration | Un fichier `kiese-<date>.sqlite3.gz` daté de juste avant la mise à jour existe dans `%APPDATA%\KIESE\backups\` | | |
| 6.6 | Simuler un échec de migration (environnement de test uniquement, avec l'aide d'un agent technique) | Message d'erreur clair (BUG-073), application fermée sans boucle de redémarrage, dossier des sauvegardes ouvert automatiquement | | |

---

## 7. Restauration de sauvegarde

**Rappel** : BUG-074 ouvert au moment de la rédaction — tant qu'il n'est pas corrigé, l'étape 7.2
ne peut être testée que manuellement (copier le fichier de sauvegarde par-dessus `kiese.sqlite3`
avec l'application fermée), pas depuis un écran « Administration » de l'application.

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 7.1 | Créer une sauvegarde manuelle (si l'écran existe) ou utiliser une sauvegarde automatique existante | Fichier `.sqlite3.gz` présent et daté dans `backups\` | | |
| 7.2 | Restaurer cette sauvegarde (écran Administration une fois BUG-074 corrigé, ou procédure manuelle sinon) | Les données reviennent exactement à l'état de la sauvegarde (facture créée après la sauvegarde disparaît, celle créée avant reste) | | |

---

## 8. Désinstallation / réinstallation avec reprise des données

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 8.1 | Désinstaller via « Programmes et fonctionnalités » (ou le raccourci de désinstallation NSIS) | Désinstallation réussie, raccourcis supprimés | | |
| 8.2 | Vérifier `%APPDATA%\KIESE\` après désinstallation | Le dossier et son contenu (`kiese.sqlite3`, `backups\`, `logs\`, `config.json`) **existent toujours** (`deleteAppDataOnUninstall: false`, DESKTOP.md §8) | | |
| 8.3 | Réinstaller la même version | Au premier lancement après réinstallation, `configExists()` trouve `config.json` existant : l'application doit démarrer directement sur la fenêtre principale, **pas** repasser par l'assistant de première installation | | |
| 8.4 | Vérifier les données après réinstallation | Les factures/clients créés avant la désinstallation sont toujours visibles | | |

---

## 9. Changement d'heure système

| # | Étape | Résultat attendu | OK/KO | Observation |
|---|---|---|---|---|
| 9.1 | Avancer l'horloge Windows d'un jour, créer une facture | La date de facture reflète la nouvelle date système (horodatage serveur local, pas de blocage) | | |
| 9.2 | Reculer l'horloge Windows (ex. revenir à la veille) | Documenter le comportement observé : une facture datée « avant » une facture déjà existante peut perturber des calculs qui supposent un ordre chronologique (BP cumulatif, §5.2 CLAUDE.md) — à signaler en ticket si un calcul produit un résultat incohérent, pas seulement « inhabituel » | | |
| 9.3 | Remettre l'heure correcte | L'application continue de fonctionner normalement, aucune donnée corrompue | | |

---

## Clôture de la session de test

- Reporter chaque case KO en ticket `BUG-NNN` (composant `desktop`) dans
  `docs/qa/REGISTRE_BUGS.md`, avec capture d'écran si pertinent dans `docs/qa/captures/`.
- Indiquer la version testée (`KIESE-Setup-<version>.exe`), la version de Windows exacte (10 ou 11,
  build), et le modèle de PC pour chaque ligne.
- Rapport de synthèse de la session : `docs/qa/rapports/testeur-installation-<date>.md`.
