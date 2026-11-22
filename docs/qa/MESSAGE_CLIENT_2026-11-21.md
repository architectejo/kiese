# Message à envoyer au propriétaire — 21/11/2026

*Rédigé pour le propriétaire de l'ETS. KIESE (pas un technicien). Une réponse courte suffit, par exemple : « Q1 : A ; Q2 : B ». Les montants sont des exemples inventés, calculés avec les vraies règles de l'application. Détail et chiffres complets : `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md` (Q-022 à Q-027).*

---

Bonjour,

L'application est presque terminée. Il reste **6 questions** auxquelles seul vous pouvez répondre. Tant qu'elles n'ont pas de réponse, nous gardons le fonctionnement actuel, mais nous ne pouvons pas fermer ces points.

## Paie des commissions

**Q1. Quand la commission d'un client ne couvre pas ses retenues, que fait-on du manque ?**
Exemple : commission 5 000 FC, dette 6 000 FC, cotisation sociale 3 000 FC. Il manque 4 000 FC.
- **A.** (aujourd'hui) On reporte ces 4 000 FC sur le mois suivant. Le mois suivant, le client reçoit 8 000 FC au lieu de 12 000 FC.
- **B.** On oublie le manque : rien n'est reporté. Le mois suivant, il reçoit 12 000 FC.
- **C.** Le client paie les 4 000 FC en espèces tout de suite. Le mois suivant, il reçoit 12 000 FC.

**Q2. L'épargne d'un client doit-elle s'ajouter à sa commission ?**
Exemple : un client a 7 000 FC d'épargne chez nous et achète quand même 4 000 FC de pain (commission 1 000 FC, cotisation 3 000 FC).
- **A.** (aujourd'hui, comme vos classeurs Excel) L'épargne s'ajoute : il reçoit 5 000 FC.
- **B.** L'épargne n'entre jamais dans la paie : il reçoit −2 000 FC (manque reporté, voir Q1).

**Q3. Une dette peut-elle être comptée deux fois ?**
Exemple : commission 5 000 FC, dette 10 000 FC, cotisation 3 000 FC, le même mois deux fois de suite.
- **A.** (aujourd'hui) La dette n'est comptée qu'une fois : −8 000 FC chaque mois.
- **B.** (ancien fonctionnement) Dette et report comptés ensemble : −16 000 FC le deuxième mois.

## Réglages propres à chaque boulangerie

**Q4. Quelles valeurs doivent être propres à chaque boulangerie ?**
Aujourd'hui, seule la **cotisation sociale** est réglée boulangerie par boulangerie. Le **taux de commission par défaut (25 %)** et les **frais d'imprimés** sont les mêmes partout. Le **frais de carte** est à 0 depuis votre décision du 14/11 (« on n'a plus besoin de carte client »), alors qu'une remarque plus ancienne demandait de le prendre en compte.
- **A.** Garder ainsi : seule la cotisation sociale change d'une boulangerie à l'autre. Pas de frais de carte.
- **B.** Le taux de commission et les frais d'imprimés deviennent aussi propres à chaque boulangerie. Pas de frais de carte.
- **C.** Comme B, et on rétablit un frais de carte, réglable pour chaque boulangerie.

## Le livreur

**Q5. Le livreur doit-il voir les clients des autres boulangeries ?**
Un client de K3 se présente à K1. Le facturier de K1 peut le chercher et lui faire sa facture (vous l'avez demandé). Aujourd'hui le livreur voit la même chose (nom, code, solde), en lecture seule.
- **A.** (aujourd'hui) Oui, comme le facturier : il retrouve tout de suite un client venu d'ailleurs.
- **B.** Non, seulement les clients de sa boulangerie : pour un client venu d'ailleurs, c'est le facturier ou le gérant qui s'en occupe.

**Q6. Quels écrans le livreur doit-il avoir ?**
Aujourd'hui il peut confirmer des livraisons, mais son menu est presque vide. Cochez ce qu'il doit pouvoir faire : voir les livraisons en attente de sa boulangerie ; confirmer une livraison ; déclarer « non servi » ; chercher un client ; annuler les factures en attente périmées. Ajoutez ce qui manque.

---

Merci. Dès votre réponse, nous réglons chaque point en une journée environ.
