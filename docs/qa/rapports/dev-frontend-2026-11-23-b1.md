# dev-frontend, B-1 (BUG-1103), 2026-11-23

## Fait
- `api/services.ts` et `pages/dashboard/Nodes.tsx` : `default_commission_rate?: string | null` sur `BakeryNode`.
- `Nodes.tsx` : champ « Taux de commission par défaut » (nombre, 0 à 0,30, pas 0,01, vide = taux global). L'aide « Vide = taux global (x %) » lit la configuration (`coreApi.config.get`) ou affiche un texte générique si la lecture échoue. Vide : envoie `null` ; sinon une chaîne décimale. Contrôle local de la borne, et l'erreur 400 du serveur s'affiche telle quelle sous le champ.
- `Clients.tsx` : à l'ouverture de la modale de création, le taux (en %) est pré-rempli avec celui de la boulangerie choisie ou de l'utilisateur, sinon avec le taux global. Il ne change plus dès que l'utilisateur modifie le champ. Le formulaire envoie toujours `commission_rate` (champ existant, libre de 0 à 100 %) : la limite 25/30 n'existait pas, rien changé.
- La liste des boulangeries est maintenant chargée à l'ouverture pour tous les rôles (avant : seulement sans boulangerie rattachée).

## Non vérifié visuellement
- Rendu à 360 / 768 / 1440 px. Le champ est un bloc simple pleine largeur comme ses voisins, donc sans risque de débordement attendu.
- Le gérant peut ne pas avoir le droit de lire `/api/core/config/` ou la liste des nœuds : dans ce cas le pré-remplissage retombe sur 25 %.
- Aucun test E2E exécuté.

## Vérification manuelle
1. Boulangerie > modifier : saisir 0,30, enregistrer, rouvrir : 0,30. Vider : retour au taux global. Saisir 0,5 : message d'erreur.
2. Clients > Créer : choisir une boulangerie à 0,30, le taux passe à 30. Modifier à la main, changer de boulangerie : la valeur saisie reste.
