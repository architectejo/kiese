"""
Dates de travail et rotation d'équipes (BUG-161, décision client du 2026-11-12).

DÉCISION CLIENT (2026-11-12, remplace « journée de travail de relève à
relève ») : la date de travail d'une boulangerie est TOUJOURS le JOUR
CALENDAIRE local, de minuit à minuit (`TIME_ZONE`, `Africa/Kinshasa`),
même quand `Node.team_rotation_enabled` est actif. Une vente à 03:00 est du
jour calendaire, pas de la veille. Un jour calendaire = UN SEUL rapport de
clôture journalier par boulangerie, partagé par les deux équipes, et UNE
clôture de caisse par nœud et par date.

La ROTATION reste un concept d'ÉQUIPE seulement : à l'heure de relève
(`Node.handover_time`) l'équipe de service change. Une « période de service »
court de la relève du jour J (incluse) à la relève du jour J+1 (exclue) ; elle
est identifiée par sa « date de période » (`business_date`/`shift_date` = date
locale de sa relève de début). La désignation manuelle d'équipe
(`DailyTeamAssignment.work_date`) est rattachée à cette date de période : la
colonne `work_date` du modèle porte donc la date de la RELÈVE, pas la date de
travail. Aucune migration de données n'est nécessaire (c'est la sémantique
historique de la colonne).

Toutes les fonctions raisonnent en heure locale du projet et ne dépendent que
du nœud. Ce module est purement fonctionnel (aucune écriture en base).
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
    DATE DE PÉRIODE DE SERVICE (et non date de travail) de `node` à l'instant
    donné : avant l'heure de relève locale, on est encore dans la période
    démarrée la veille. Sert uniquement à rattacher la désignation d'équipe.
    Si la relève est à 00:00, c'est la date calendaire locale.
    """
    local = _local_instant(instant)
    if local.time() < node.handover_time:
        return local.date() - timedelta(days=1)
    return local.date()


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
    SOURCE UNIQUE de la « date de travail » côté serveur : la DATE LOCALE
    calendaire (`TIME_ZONE`), avec ou sans rotation d'équipes (décision client
    2026-11-12). Jamais de `.date()` sur un datetime aware non converti
    (BUG-189). `node` est conservé dans la signature pour les appelants ;
    `node=None` (utilisateur HQ sans boulangerie) donne le même résultat.
    """
    return _local_instant(instant).date()


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
    aware) tombe dans la date calendaire locale `work_date` (conversion
    locale par Django). Identique avec ou sans rotation (décision 2026-11-12).
    """
    return {f'{field}__date': work_date}


def workday_bounds(node, work_date):
    """
    (début, fin) de la PÉRIODE DE SERVICE de date `work_date` : début inclus
    (relève de `work_date`), fin exclue (relève de `work_date` + 1 jour).
    Datetimes aware, fuseau local du projet. Invariant :
    business_date(node, t) == work_date  <=>  début <= t < fin.
    """
    start = _at(work_date, node.handover_time)
    end = _at(work_date + timedelta(days=1), node.handover_time)
    return start, end


def shift_period_start(node, instant=None):
    """Début (aware, local) de la période de service en cours à `instant`."""
    return workday_bounds(node, business_date(node, instant))[0]


def next_handover(node, instant=None):
    """Prochain instant de relève strictement postérieur à `instant` (aware, local)."""
    local = _local_instant(instant)
    candidate = _at(local.date(), node.handover_time)
    if candidate <= local:
        candidate = _at(local.date() + timedelta(days=1), node.handover_time)
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


def team_at_day_start(node, calendar_date):
    """
    Équipe de service à 00:00 du jour calendaire `calendar_date` : celle de la
    période démarrée la veille si la relève est après minuit, sinon celle de
    la période démarrée ce jour-là (relève à 00:00). `None` sans désignation.
    C'est l'équipe qui porte le « reste du hier » du rapport journalier.
    """
    if node.handover_time == datetime.min.time():
        return team_for_work_date(node, calendar_date)
    # Période démarrée la veille ; à défaut (pas de désignation à cette date,
    # ex. première mise en rotation), équipe de la première période du jour.
    return (
        team_for_work_date(node, calendar_date - timedelta(days=1))
        or team_for_work_date(node, calendar_date)
    )


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
