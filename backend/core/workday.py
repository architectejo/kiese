"""
Journée de travail « de relève à relève » (BUG-161, étape B1).

Une journée de travail d'une boulangerie court de l'heure de relève
(`Node.handover_time`) du jour J à la même heure du jour J+1. Tout instant
situé avant la relève appartient à la journée de travail de la veille
(ex. relève 12:00 : 2026-11-12 03:00 appartient à la journée du 2026-11-11).

Toutes les fonctions raisonnent en heure locale du projet (`TIME_ZONE`,
`Africa/Kinshasa`, `USE_TZ=True`) et ne dépendent que du nœud : deux
boulangeries ayant des heures de relève différentes ont des journées de
travail différentes au même instant.

Ce module est purement fonctionnel (aucune écriture en base).
"""
from datetime import datetime, timedelta

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


def business_date(node, instant=None):
    """
    Date de la journée de travail de `node` à l'instant donné (défaut : maintenant).
    Avant l'heure de relève (locale), on est encore dans la journée de la veille.
    Si la relève est à 00:00, le résultat est toujours la date calendaire locale.
    """
    local = _local_instant(instant)
    if local.time() < node.handover_time:
        return local.date() - timedelta(days=1)
    return local.date()


def work_date_for(node, instant=None):
    """
    BUG-161 (B3) : SOURCE UNIQUE de la « date de travail » côté serveur.

    - Boulangerie en mode rotation (`Node.team_rotation_enabled`) : journée de
      relève à relève, `business_date(node, instant)`.
    - Sinon (comportement historique, strictement inchangé) : date LOCALE du
      calendrier (`TIME_ZONE`), comme `timezone.localdate()`.

    Dans les deux cas la date est calculée en heure locale du projet : jamais
    de `.date()` sur un datetime aware non converti (BUG-189). `node=None`
    (utilisateur HQ sans boulangerie) retombe sur la date locale.
    """
    if node is not None and getattr(node, 'team_rotation_enabled', False):
        return business_date(node, instant)
    return _local_instant(instant).date()


def work_time_info(node, instant=None):
    """
    BUG-161 (B3) : `{"work_date": "AAAA-MM-JJ", "server_now": "<ISO>"}` à
    ajouter (de façon additive) aux réponses consommées par le frontend, pour
    qu'il n'utilise plus `new Date().toISOString().slice(0, 10)` (date UTC,
    fausse entre 00:00 et 01:00 à Kinshasa).
    """
    local = _local_instant(instant)
    return {
        'work_date': work_date_for(node, instant).isoformat(),
        'server_now': local.isoformat(),
    }


def delivered_on_work_date_filter(node, work_date, field='delivered_at'):
    """
    BUG-161 (B3) : filtre ORM (dict de lookups) des enregistrements dont
    `field` (datetime aware) tombe dans la journée de travail `work_date` de
    `node`. Hors rotation : `<field>__date` (conversion locale par Django,
    comportement historique) ; en rotation : bornes de relève à relève.
    """
    if node is not None and getattr(node, 'team_rotation_enabled', False):
        start, end = workday_bounds(node, work_date)
        return {f'{field}__gte': start, f'{field}__lt': end}
    return {f'{field}__date': work_date}


def workday_bounds(node, work_date):
    """
    (début, fin) de la journée de travail `work_date` : début inclus
    (relève de `work_date`), fin exclue (relève de `work_date` + 1 jour).
    Datetimes aware, fuseau local du projet. Invariant :
    business_date(node, t) == work_date  <=>  début <= t < fin.
    """
    start = _at(work_date, node.handover_time)
    end = _at(work_date + timedelta(days=1), node.handover_time)
    return start, end


def next_handover(node, instant=None):
    """Prochain instant de relève strictement postérieur à `instant` (aware, local)."""
    local = _local_instant(instant)
    candidate = _at(local.date(), node.handover_time)
    if candidate <= local:
        candidate = _at(local.date() + timedelta(days=1), node.handover_time)
    return candidate


def current_team(node, instant=None):
    """
    BUG-161 (B2) : équipe de service désignée pour la journée de travail de
    `node` à `instant` (défaut : maintenant), ou `None` si aucune désignation.
    Lecture seule. Import local de `production.models` pour éviter un import
    circulaire (production dépend de core).
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
    BUG-161 (B4/B5) : équipe désignée pour la journée de travail `work_date`
    (quelconque, passée ou courante), ou `None`. Lecture seule.
    """
    from production.models import DailyTeamAssignment

    return (
        DailyTeamAssignment.objects
        .filter(node=node, work_date=work_date)
        .values_list('team', flat=True)
        .first()
    )


def suggested_team(node, instant=None):
    """
    Pré-sélection (simple suggestion modifiable, pas une règle) : l'autre
    équipe que celle désignée à la journée de travail précédente, ou 'A' s'il
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
