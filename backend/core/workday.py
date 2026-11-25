"""
Journée comptable de MIDI À MIDI (BUG-1130, réponse client Q-018 du 2026-11-24).

DÉCISION CLIENT (2026-11-24, remplace celle du 2026-11-12 « jour calendaire ») :
la journée (clôture, rapport, versement, restes) va de l'HEURE DE CLÔTURE de la
boulangerie (`Node.handover_time`, 12:00 par défaut) au jour D à la même heure
au jour D+1, pour toutes les boulangeries (rotation de 24 h, Q-017).

« DATE DE JOURNÉE COMPTABLE » = date calendaire locale du DÉBUT de période : la
journée D court de D 12:00 (incluse) à D+1 12:00 (exclue) ; une vente à D+1 09:00
appartient à la journée D. Toute date « du jour » côté serveur (facture,
rapport facturier, clôture de caisse, session de production, dépense...) passe
par `business_day_for` / `work_date_for` ; toute fenêtre horaire d'une journée
par `business_day_bounds` / `delivered_on_work_date_filter`. Un nœud absent
(utilisateur siège) ou sans heure de clôture valide utilise 12:00.

La désignation d'équipe (`DailyTeamAssignment.work_date`) garde sa colonne :
elle porte la date de la période de service, qui coïncide désormais avec la
journée comptable. Aucune réécriture des données passées (voir
docs/qa/CONCEPTION_JOURNEE_MIDI_A_MIDI_2026-11-24.md).

Toutes les fonctions raisonnent en heure locale du projet (`TIME_ZONE`,
`Africa/Kinshasa`) et ne dépendent que du nœud. Module purement fonctionnel.
"""
from datetime import datetime, time, timedelta

from django.utils import timezone


def _local_instant(instant=None):
    """Instant fourni (aware ou naïf, ce dernier supposé local) -> datetime local aware."""
    if instant is None:
        return timezone.localtime(timezone.now())
    if timezone.is_naive(instant):
        return timezone.make_aware(instant, timezone.get_current_timezone())
    return timezone.localtime(instant)


def _at(work_date, node_time):
    """Date + heure locale -> datetime aware dans le fuseau courant."""
    return timezone.make_aware(
        datetime.combine(work_date, node_time), timezone.get_current_timezone()
    )


DEFAULT_CLOSURE_TIME = time(12, 0)


def closure_time_for(node):
    """Heure de clôture (début de journée comptable) du nœud ; 12:00 si absente/invalide."""
    value = getattr(node, 'handover_time', None) if node is not None else None
    if isinstance(value, datetime):
        value = value.time()
    if not isinstance(value, time):
        return DEFAULT_CLOSURE_TIME
    return value.replace(tzinfo=None)


def business_day_for(node, instant=None):
    """
    DATE DE JOURNÉE COMPTABLE de `node` à `instant` (défaut : maintenant) :
    date locale du début de la période de midi à midi qui contient l'instant.
    08:59 le 25 -> journée du 24 ; 12:00 le 25 -> journée du 25.
    """
    local = _local_instant(instant)
    if local.time() < closure_time_for(node):
        return local.date() - timedelta(days=1)
    return local.date()


def business_day_bounds(node, work_date):
    """(début inclus, fin exclue) de la journée comptable `work_date` (aware, local)."""
    closure = closure_time_for(node)
    try:
        end = _at(work_date + timedelta(days=1), closure)
    except OverflowError:
        # 9999-12-31 : pas de lendemain représentable ; borne haute = fin des temps
        # (jamais de 500 sur une date extrême saisie dans une URL).
        end = timezone.make_aware(datetime.max, timezone.get_current_timezone())
    return _at(work_date, closure), end


def business_date(node, instant=None):
    """
    DATE DE PÉRIODE DE SERVICE (et non date de travail) de `node` à l'instant
    donné : avant l'heure de relève locale, on est encore dans la période
    démarrée la veille. Sert uniquement à rattacher la désignation d'équipe.
    Si la relève est à 00:00, c'est la date calendaire locale.
    """
    return business_day_for(node, instant)


def shift_date(node, instant=None):
    """
    Clé de rattachement de la désignation d'équipe à `instant` : date de
    période (`business_date`) en rotation ; date calendaire locale sinon
    (BUG-227 : hors rotation la désignation reste calendaire).
    """
    if node is not None and getattr(node, 'team_rotation_enabled', False):
        return business_date(node, instant)
    return _local_instant(instant).date()


def work_date_for(node, instant=None):
    """
    SOURCE UNIQUE de la « date de travail » côté serveur : la date de JOURNÉE
    COMPTABLE de midi à midi (`business_day_for`). Jamais de `.date()` sur un
    datetime aware non converti (BUG-189). `node=None` (utilisateur siège) :
    heure de clôture par défaut 12:00.
    """
    return business_day_for(node, instant)


def work_time_info(node, instant=None):
    """
    `{"work_date": "AAAA-MM-JJ", "server_now": "<ISO>"}` à ajouter (de façon
    additive) aux réponses consommées par le frontend, pour qu'il n'utilise
    plus `new Date().toISOString().slice(0, 10)` (date UTC, fausse entre 00:00
    et 01:00 à Kinshasa). `work_date` = date calendaire locale du serveur.
    """
    local = _local_instant(instant)
    return {
        'work_date': work_date_for(node, instant).isoformat(),
        'server_now': local.isoformat(),
    }


def delivered_on_work_date_filter(node, work_date, field='delivered_at'):
    """
    Filtre ORM (dict de lookups) des enregistrements dont `field` (datetime
    aware) tombe dans la journée comptable `work_date` de `node` : de l'heure
    de clôture du jour D (incluse) à celle du jour D+1 (exclue).
    """
    start, end = business_day_bounds(node, work_date)
    return {f'{field}__gte': start, f'{field}__lt': end}


def workday_bounds(node, work_date):
    """Alias historique de `business_day_bounds` (début inclus, fin exclue)."""
    return business_day_bounds(node, work_date)


def instant_in_business_day(node, work_date, now=None):
    """
    Instant (aware) de la journée comptable `work_date` situé au MÊME décalage
    depuis le début de journée que `now` dans la journée courante. Sert aux
    ventes rétroactives sans heure explicite : `delivered_at` doit tomber dans
    la journée demandée (jamais `date + heure courante`, qui peut tomber dans
    la journée voisine).
    """
    local = _local_instant(now)
    offset = local - business_day_bounds(node, business_day_for(node, local))[0]
    return business_day_bounds(node, work_date)[0] + offset


def shift_period_start(node, instant=None):
    """Début (aware, local) de la période de service en cours à `instant`."""
    return workday_bounds(node, business_date(node, instant))[0]


def next_handover(node, instant=None):
    """Prochain instant de relève strictement postérieur à `instant` (aware, local)."""
    local = _local_instant(instant)
    candidate = _at(local.date(), closure_time_for(node))
    if candidate <= local:
        candidate = _at(local.date() + timedelta(days=1), closure_time_for(node))
    return candidate


def current_team(node, instant=None):
    """
    Équipe de service désignée pour la période de service de `node` à
    `instant` (défaut : maintenant), ou `None` si aucune désignation. Toujours
    la période de relève (`business_date`) ; seule la vue de désignation
    (`shift_date`) reste calendaire hors rotation (BUG-227). Lecture seule. Import local de `production.models` (import circulaire).
    """
    from production.models import DailyTeamAssignment

    return (
        DailyTeamAssignment.objects
        .filter(node=node, work_date=business_date(node, instant))
        .values_list('team', flat=True)
        .first()
    )


def team_for_work_date(node, work_date):
    """
    Équipe désignée pour la période de service dont la DATE DE PÉRIODE
    (date de la relève de début) est `work_date`, ou `None`. Lecture seule.
    Nom historique conservé ; voir `team_at_day_start` pour le rapport
    journalier calendaire.
    """
    from production.models import DailyTeamAssignment

    return (
        DailyTeamAssignment.objects
        .filter(node=node, work_date=work_date)
        .values_list('team', flat=True)
        .first()
    )


def team_at_day_start(node, work_date):
    """
    Équipe de service au DÉBUT de la journée comptable `work_date` (midi à midi,
    BUG-1130) : celle de la période de service qui démarre à l'heure de clôture
    de ce jour. `None` sans désignation. C'est l'équipe qui porte le « reste
    d'hier » du rapport journalier.
    """
    return team_for_work_date(node, work_date)


def suggested_team(node, instant=None):
    """
    Pré-sélection (simple suggestion modifiable, pas une règle) : l'autre
    équipe que celle désignée à la période de service précédente, ou 'A' s'il
    n'y a pas d'historique.
    """
    from production.models import DailyTeamAssignment

    previous = (
        DailyTeamAssignment.objects
        .filter(node=node, work_date__lt=business_date(node, instant))
        .order_by('-work_date')
        .values_list('team', flat=True)
        .first()
    )
    if previous == 'A':
        return 'B'
    return 'A'
