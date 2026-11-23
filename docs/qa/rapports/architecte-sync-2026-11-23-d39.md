# architecte-sync d39 (Dev B) - 2026-11-23 : BUG-974 a 980 (synchronisation des transferts)

Tickets passes a CORRIGE : 974, 975, 976, 977, 978, 979, 980. Les 9 `@expectedFailure` de
`production/tests/test_verif_production_a13_v13.py` sont retires (assertions inchangees) et passent.
Lot lance : a13, a12, a11, a10, a9, a8, a7, a6, sync v5 / charge v4 / bug004, transferts existants (357 tests) : OK
(1 echec attendu preexistant hors transferts) ; `makemigrations --check` : aucune migration manquante.
Log : `%TEMP%/d39.log`. Hors perimetre respecte : ni `sales/`, ni `treasury/views`.

## Contrat final

### Export (poste -> cloud, `build_outbound_payload`)
- `production.BreadTransfer` exporte aussi `flow` (977).
- Champ de tete `open_transfers` : ids des transferts non terminaux (ni CONFIRMED ni CANCELLED) dont le poste est
  emettrice ou receptrice (980). Hors `records`, donc hors empreinte du lot.

### Push (cloud, `sync/services.py`)
- Creation : `flow = DIRECT` seulement pour un envoi direct de l'emettrice (RESPONDED a la creation, sans quantite
  recue), y compris d'un poste ancien sans `flow` ; sinon REQUEST (977).
- Ligne d'un transfert DISPUTED, poussee par l'EMETTRICE uniquement (974) :
  - `quantity_sent` accepte si egale a la `quantity_received` declaree par la receptrice (ALIGN_ON_RECEIVED) ;
  - `quantity_received` accepte si egale a `quantity_sent` (ALIGN_ON_SENT) ;
  - tout autre ecart reste refuse (BUG-788/920 inchange). Restrictions de role 874/888/891/921/928/966 inchangees.
- Le transfert (passage DISPUTED -> CONFIRMED par l'emettrice) est traite avant ses lignes dans le lot : au 1er cycle
  il est refuse (« litige non resolu »), les lignes sont acceptees, il est accepte au 2e cycle (convergence en 2 cycles,
  sans perte : l'enregistrement refuse reste `is_synced=False`).
- Le push memorise `open_transfers` (modele `sync.NodeOpenTransfers`, ids UUID valides, max 1000, ignore si absent).

### Pull (cloud -> poste, `PullView`)
- Ajoute `node_code` (identite du jeton) ; le poste s'en sert pour son role emettrice/receptrice (a defaut `KIESE_NODE_CODE`,
  sinon aucun effet de stock ni alerte).
- Transferts de l'emettrice ou receptrice. Un transfert CONFIRMED/CANCELLED inactif depuis > 30 jours n'est descendu que
  si le poste l'a declare non terminal (`open_transfers`) ; l'id est retire une fois livre, et redeclare au push suivant si le
  poste ne l'a pas applique (reponse perdue) (980). Pas de nouvel accuse ni de changement de signature de pull.

### Application locale (`_apply_pulled_transfers`)
- Inconnu : cree (statut, `flow` du cloud), lignes copiees SANS mouvement de stock.
- Connu : ignore si `is_synced=False`, si deja terminal, ou si le statut cloud est inferieur au local. Sinon les lignes
  sont appliquees des que statut cloud >= local (979 : lignes manquantes creees, quantites mises a jour a statut egal) ;
  le statut n'avance que s'il est superieur (975 : `quantity_sent` desormais applique).
- Stock miroir (976) par DELTA ligne cloud - ligne locale, dans la meme transaction que l'ecriture de la ligne :
  receptrice `received += delta_recu` ; emettrice `sent += delta_envoye` seulement si la copie locale etait deja
  RESPONDED/DISPUTED. La ligne locale tient lieu de marqueur d'application : un pull rejoue donne un delta nul, jamais de
  double mouvement ; aucun marqueur ni migration sur les transferts n'etait necessaire. Resultat : somme du groupe
  100 apres ALIGN_ON_RECEIVED (K1 +2), ALIGN_ON_SENT (K2 +2) et confirmation par le siege (K2 +100).
- Alertes (978), choix : regeneration locale a l'application du pull (pas de synchronisation de `SystemNotification`,
  plus lourde et a risque de doublons/fuite entre postes). Une fois par poste car creation/avance de statut n'ont lieu qu'une
  fois : « Demande de Pains » (emettrice, nouvelle PENDING), « Pains Envoyes » (receptrice, RESPONDED), « Litige Transfert »
  (emettrice, DISPUTED), « Litige resolu » (DISPUTED -> CONFIRMED), « Demande Refusee » (receptrice, CANCELLED).

### Migration additive
`sync/migrations/0003_nodeopentransfers.py` (nouvelle table, `NodeOpenTransfers`). Aucun changement de table existante.

## Limites / A CLARIFIER (decision metier, non tranchees)
1. Transfert inconnu d'un poste et deja CONFIRME au cloud avec quantites recues (siege confirme pour une receptrice qui n'a
   jamais vu l'envoi) : la copie est creee sans credit de stock (on ne peut distinguer ce cas d'un poste reinstalle/neuf qui
   rejouerait tout l'historique). Le siege devrait attendre que K2 ait vu l'envoi, ou regulariser par ajustement manuel.
2. Reponse positive faite AU CLOUD (siege) a une demande PENDING : l'emettrice, en voyant RESPONDED par pull, n'est pas
   debitee (le stock physique ne peut etre decide a sa place). Hors perimetre a13.
3. Les alertes siege (`node_origin='CLOUD'`) restent celles du cloud.
