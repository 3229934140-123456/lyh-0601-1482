import json
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

from models import ConsistencyLevel


def _hash_value(value: Any) -> str:
    if isinstance(value, dict):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    elif isinstance(value, list):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(str(value).encode('utf-8')).hexdigest()


def _compare_values(v1: Any, v2: Any) -> bool:
    if v1 is None and v2 is None:
        return True
    if v1 is None or v2 is None:
        return False
    if isinstance(v1, dict) and isinstance(v2, dict):
        if set(v1.keys()) != set(v2.keys()):
            return False
        return all(_compare_values(v1[k], v2[k]) for k in v1.keys())
    if isinstance(v1, list) and isinstance(v2, list):
        if len(v1) != len(v2):
            return False
        return sorted([_hash_value(x) for x in v1]) == sorted([_hash_value(x) for x in v2])
    return v1 == v2


def _find_majority_annotation(annotations: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Counter]:
    if not annotations:
        return None, Counter()

    annotation_hashes = []
    for ann in annotations:
        content = ann.get('content', {}) if isinstance(ann, dict) else getattr(ann, 'content', {})
        annotation_hashes.append((_hash_value(content), content))

    hash_counter = Counter(h for h, _ in annotation_hashes)
    if not hash_counter:
        return None, hash_counter

    most_common_hash, _ = hash_counter.most_common(1)[0]

    for h, content in annotation_hashes:
        if h == most_common_hash:
            return content, hash_counter

    return None, hash_counter


def calculate_consistency(annotations: List[Any], label_specs: Optional[List[Any]] = None) -> Dict[str, Any]:
    if not annotations:
        return {
            'consistency_score': 0.0,
            'consistency_level': ConsistencyLevel.LOW,
            'conflict_fields': [],
            'is_consistent': False,
            'majority_annotation': None
        }

    contents = []
    for ann in annotations:
        if isinstance(ann, dict):
            contents.append(ann.get('content', {}))
        else:
            contents.append(getattr(ann, 'content', {}))

    if len(contents) < 2:
        return {
            'consistency_score': 1.0 if len(contents) == 1 else 0.0,
            'consistency_level': ConsistencyLevel.HIGH if len(contents) == 1 else ConsistencyLevel.LOW,
            'conflict_fields': [],
            'is_consistent': True,
            'majority_annotation': contents[0] if contents else None
        }

    all_keys = set()
    for content in contents:
        if isinstance(content, dict):
            all_keys.update(content.keys())

    conflict_fields = []
    field_consistency_scores = []

    spec_keys = set()
    if label_specs:
        for spec in label_specs:
            if isinstance(spec, dict):
                spec_keys.add(spec.get('name', ''))
            else:
                spec_keys.add(getattr(spec, 'name', ''))

    check_keys = spec_keys if spec_keys else all_keys

    for key in check_keys:
        key_values = [content.get(key) for content in contents]
        unique_count = len(set(_hash_value(v) for v in key_values))

        if unique_count == 1:
            field_consistency_scores.append(1.0)
        else:
            conflict_fields.append(key)
            most_common_count = Counter(_hash_value(v) for v in key_values).most_common(1)[0][1]
            field_consistency_scores.append(most_common_count / len(key_values))

    if not field_consistency_scores:
        consistency_score = 1.0 if len(set(_hash_value(c) for c in contents)) == 1 else 0.0
    else:
        consistency_score = sum(field_consistency_scores) / len(field_consistency_scores)

    if consistency_score >= 0.9:
        consistency_level = ConsistencyLevel.HIGH
    elif consistency_score >= 0.7:
        consistency_level = ConsistencyLevel.MEDIUM
    else:
        consistency_level = ConsistencyLevel.LOW

    majority_annotation, _ = _find_majority_annotation(
        [{'content': c} for c in contents]
    )

    return {
        'consistency_score': round(consistency_score, 4),
        'consistency_level': consistency_level,
        'conflict_fields': conflict_fields,
        'is_consistent': not conflict_fields,
        'majority_annotation': majority_annotation
    }


def check_annotation_consistency(
    annotations: List[Any],
    threshold: float = 0.8,
    label_specs: Optional[List[Any]] = None
) -> Dict[str, Any]:
    result = calculate_consistency(annotations, label_specs)
    result['is_consistent'] = result['consistency_score'] >= threshold
    return result


def calculate_pairwise_consistency(annotations: List[Any]) -> List[Dict[str, Any]]:
    results = []
    contents = []
    annotator_ids = []

    for ann in annotations:
        if isinstance(ann, dict):
            contents.append(ann.get('content', {}))
            annotator_ids.append(ann.get('annotator_id'))
        else:
            contents.append(getattr(ann, 'content', {}))
            annotator_ids.append(getattr(ann, 'annotator_id'))

    for i in range(len(contents)):
        for j in range(i + 1, len(contents)):
            c1, c2 = contents[i], contents[j]
            all_keys = set(c1.keys()) | set(c2.keys())
            matches = 0
            total = len(all_keys) if all_keys else 1

            for key in all_keys:
                if _compare_values(c1.get(key), c2.get(key)):
                    matches += 1

            score = matches / total if total > 0 else 1.0

            results.append({
                'annotator_1': annotator_ids[i],
                'annotator_2': annotator_ids[j],
                'consistency_score': round(score, 4)
            })

    return results
