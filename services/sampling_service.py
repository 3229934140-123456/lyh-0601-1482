import random
from typing import List, Any, Optional, Dict
from datetime import datetime, timedelta


def stratified_sampling(
    items: List[Any],
    sample_count: int,
    stratify_key: Optional[str] = None,
    seed: Optional[int] = None
) -> List[Any]:
    if not items:
        return []

    if seed is not None:
        random.seed(seed)

    if sample_count >= len(items):
        return items[:]

    if not stratify_key:
        return random.sample(items, sample_count)

    strata: Dict[str, List[Any]] = {}
    for item in items:
        if isinstance(item, dict):
            key = str(item.get(stratify_key, 'default'))
        else:
            key = str(getattr(item, stratify_key, 'default'))
        if key not in strata:
            strata[key] = []
        strata[key].append(item)

    total = len(items)
    strata_ratios = {k: len(v) / total for k, v in strata.items()}

    sampled = []
    remaining = sample_count

    strata_items = list(strata.items())
    random.shuffle(strata_items)

    for i, (key, stratum_items) in enumerate(strata_items):
        if i == len(strata_items) - 1:
            count = remaining
        else:
            count = max(1, int(sample_count * strata_ratios[key]))
            count = min(count, len(stratum_items), remaining)

        if count > 0 and len(stratum_items) > 0:
            if count >= len(stratum_items):
                sampled.extend(stratum_items)
            else:
                sampled.extend(random.sample(stratum_items, count))
            remaining -= count

        if remaining <= 0:
            break

    if remaining > 0:
        all_items = [item for item in items if item not in sampled]
        if all_items:
            extra = min(remaining, len(all_items))
            sampled.extend(random.sample(all_items, extra))

    return sampled[:sample_count]


def sample_quality_checks(
    samples: List[Any],
    sample_rate: float = 0.1,
    min_samples: int = 1,
    max_samples: Optional[int] = None,
    prioritize_conflict: bool = True,
    seed: Optional[int] = None
) -> List[Any]:
    if not samples:
        return []

    if seed is not None:
        random.seed(seed)

    target_count = max(min_samples, int(len(samples) * sample_rate))
    if max_samples:
        target_count = min(target_count, max_samples)

    if target_count >= len(samples):
        return samples[:]

    conflict_samples = []
    normal_samples = []

    for s in samples:
        if isinstance(s, dict):
            status = s.get('status', '')
            consistency = s.get('consistency_score', 1.0)
        else:
            status = str(getattr(s, 'status', ''))
            consistency = getattr(s, 'consistency_score', 1.0)

        is_conflict = (
            'conflict' in status.lower() or
            (consistency is not None and consistency < 0.7)
        )

        if prioritize_conflict and is_conflict:
            conflict_samples.append(s)
        else:
            normal_samples.append(s)

    result = []
    conflict_sample_count = min(len(conflict_samples), target_count // 2 + 1)
    if conflict_samples:
        result.extend(random.sample(conflict_samples, conflict_sample_count))

    remaining = target_count - len(result)
    if remaining > 0 and normal_samples:
        if remaining >= len(normal_samples):
            result.extend(normal_samples)
        else:
            result.extend(random.sample(normal_samples, remaining))

    if len(result) < target_count:
        extra_needed = target_count - len(result)
        all_picked_ids = set()
        for item in result:
            if isinstance(item, dict):
                all_picked_ids.add(item.get('id'))
            else:
                all_picked_ids.add(getattr(item, 'id', None))

        remaining_pool = [s for s in samples if (
            s.get('id') if isinstance(s, dict) else getattr(s, 'id', None)
        ) not in all_picked_ids]
        if remaining_pool:
            extra = min(extra_needed, len(remaining_pool))
            result.extend(random.sample(remaining_pool, extra))

    random.shuffle(result)
    return result[:target_count]


def check_lock_timeout(
    locked_at: Optional[datetime],
    timeout_seconds: int = 1800
) -> bool:
    if locked_at is None:
        return True
    now = datetime.utcnow()
    return (now - locked_at) > timedelta(seconds=timeout_seconds)


def distribute_tasks_load_balanced(
    annotators: List[Any],
    tasks_count: int,
    current_load: Optional[Dict[int, int]] = None
) -> Dict[int, int]:
    if not annotators:
        return {}

    if current_load is None:
        current_load = {}

    annotator_ids = []
    for a in annotators:
        if isinstance(a, dict):
            annotator_ids.append(a.get('id'))
        else:
            annotator_ids.append(getattr(a, 'id', None))
    annotator_ids = [aid for aid in annotator_ids if aid is not None]

    loads = {aid: current_load.get(aid, 0) for aid in annotator_ids}

    assignment: Dict[int, int] = {aid: 0 for aid in annotator_ids}

    for _ in range(tasks_count):
        min_load = min(loads.values())
        candidates = [aid for aid, load in loads.items() if load == min_load]
        chosen = random.choice(candidates)
        assignment[chosen] += 1
        loads[chosen] += 1

    return {k: v for k, v in assignment.items() if v > 0}


def calculate_priority_score(
    sample: Any,
    weight_recency: float = 0.3,
    weight_priority: float = 0.4,
    weight_wait_time: float = 0.3
) -> float:
    if isinstance(sample, dict):
        created_at = sample.get('created_at', datetime.utcnow())
        priority = sample.get('priority', 1)
        metadata = sample.get('sample_metadata', {}) or {}
    else:
        created_at = getattr(sample, 'created_at', datetime.utcnow())
        priority = getattr(sample, 'priority', 1)
        metadata = getattr(sample, 'sample_metadata', {}) or {}

    if isinstance(metadata, dict):
        priority = metadata.get('priority', priority)

    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        except ValueError:
            created_at = datetime.utcnow()

    wait_hours = max(0, (datetime.utcnow() - created_at).total_seconds() / 3600)
    recency_score = 1.0 / (1.0 + wait_hours / 24.0)
    priority_score = min(priority, 5) / 5.0
    wait_score = min(wait_hours / 72.0, 1.0)

    total_weight = weight_recency + weight_priority + weight_wait_time
    if total_weight == 0:
        total_weight = 1.0

    return (
        weight_recency * recency_score +
        weight_priority * priority_score +
        weight_wait_time * wait_score
    ) / total_weight
