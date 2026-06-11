import json
import csv
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from io import StringIO, BytesIO

from config import settings


def ensure_export_dir():
    if not os.path.exists(settings.EXPORT_DIR):
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def export_to_json(
    samples: List[Any],
    annotations: List[Any],
    project: Any,
    include_metadata: bool = True,
    label_specs: Optional[List[Any]] = None
) -> str:
    project_name = getattr(project, 'name', 'project') if not isinstance(project, dict) else project.get('name', 'project')
    project_type = getattr(project, 'project_type', 'text') if not isinstance(project, dict) else project.get('project_type', 'text')

    output = {
        'export_info': {
            'project_name': project_name,
            'project_type': project_type,
            'exported_at': datetime.utcnow().isoformat(),
            'sample_count': len(samples),
            'annotation_count': len(annotations)
        },
        'project': {
            'id': getattr(project, 'id', None) if not isinstance(project, dict) else project.get('id'),
            'name': project_name,
            'description': getattr(project, 'description', None) if not isinstance(project, dict) else project.get('description'),
            'type': project_type
        }
    }

    if include_metadata and label_specs:
        output['label_specs'] = []
        for spec in label_specs:
            output['label_specs'].append({
                'id': spec.get('id') if isinstance(spec, dict) else getattr(spec, 'id', None),
                'name': spec.get('name') if isinstance(spec, dict) else getattr(spec, 'name', ''),
                'description': spec.get('description') if isinstance(spec, dict) else getattr(spec, 'description', None),
                'value_type': spec.get('value_type') if isinstance(spec, dict) else getattr(spec, 'value_type', ''),
                'options': spec.get('options') if isinstance(spec, dict) else getattr(spec, 'options', None),
                'required': spec.get('required') if isinstance(spec, dict) else getattr(spec, 'required', True),
            })

    sample_annotations: Dict[int, List[Any]] = {}
    for ann in annotations:
        if isinstance(ann, dict):
            sid = ann.get('sample_id')
        else:
            sid = getattr(ann, 'sample_id', None)
        if sid is not None:
            if sid not in sample_annotations:
                sample_annotations[sid] = []
            sample_annotations[sid].append(ann)

    output['samples'] = []
    for sample in samples:
        if isinstance(sample, dict):
            sample_id = sample.get('id')
            sample_data = {
                'id': sample_id,
                'external_id': sample.get('external_id'),
                'content': sample.get('content'),
                'content_url': sample.get('content_url'),
                'status': str(sample.get('status', '')) if sample.get('status') else None,
                'consistency_score': sample.get('consistency_score'),
                'final_annotation': sample.get('final_annotation'),
            }
            if include_metadata:
                sample_data['metadata'] = sample.get('sample_metadata')
                sample_data['version'] = sample.get('version')
                sample_data['created_at'] = str(sample.get('created_at')) if sample.get('created_at') else None
        else:
            sample_id = getattr(sample, 'id', None)
            sample_data = {
                'id': sample_id,
                'external_id': getattr(sample, 'external_id', None),
                'content': getattr(sample, 'content', ''),
                'content_url': getattr(sample, 'content_url', None),
                'status': str(getattr(sample, 'status', '')) if getattr(sample, 'status', None) else None,
                'consistency_score': getattr(sample, 'consistency_score', None),
                'final_annotation': getattr(sample, 'final_annotation', None),
            }
            if include_metadata:
                sample_data['metadata'] = getattr(sample, 'sample_metadata', None)
                sample_data['version'] = getattr(sample, 'version', 1)
                sample_data['created_at'] = str(getattr(sample, 'created_at', None)) if getattr(sample, 'created_at', None) else None

        sample_data['annotations'] = []
        for ann in sample_annotations.get(sample_id, []):
            if isinstance(ann, dict):
                ann_data = {
                    'annotator_id': ann.get('annotator_id'),
                    'content': ann.get('content'),
                    'status': str(ann.get('status')) if ann.get('status') else None,
                    'time_spent_seconds': ann.get('time_spent_seconds'),
                    'comment': ann.get('comment'),
                }
                if include_metadata:
                    ann_data['version'] = ann.get('version')
                    ann_data['created_at'] = str(ann.get('created_at')) if ann.get('created_at') else None
                    ann_data['is_from_rework'] = ann.get('is_from_rework')
            else:
                ann_data = {
                    'annotator_id': getattr(ann, 'annotator_id', None),
                    'content': getattr(ann, 'content', {}),
                    'status': str(getattr(ann, 'status', None)) if getattr(ann, 'status', None) else None,
                    'time_spent_seconds': getattr(ann, 'time_spent_seconds', None),
                    'comment': getattr(ann, 'comment', None),
                }
                if include_metadata:
                    ann_data['version'] = getattr(ann, 'version', 1)
                    ann_data['created_at'] = str(getattr(ann, 'created_at', None)) if getattr(ann, 'created_at', None) else None
                    ann_data['is_from_rework'] = getattr(ann, 'is_from_rework', False)
            sample_data['annotations'].append(ann_data)

        output['samples'].append(sample_data)

    return json.dumps(output, ensure_ascii=False, indent=2)


def export_to_csv(
    samples: List[Any],
    annotations: List[Any],
    project: Any,
    include_metadata: bool = True,
    label_specs: Optional[List[Any]] = None
) -> str:
    output = StringIO()

    sample_annotations: Dict[int, List[Any]] = {}
    for ann in annotations:
        if isinstance(ann, dict):
            sid = ann.get('sample_id')
        else:
            sid = getattr(ann, 'sample_id', None)
        if sid is not None:
            if sid not in sample_annotations:
                sample_annotations[sid] = []
            sample_annotations[sid].append(ann)

    label_names = []
    if label_specs:
        for spec in label_specs:
            if isinstance(spec, dict):
                label_names.append(spec.get('name', ''))
            else:
                label_names.append(getattr(spec, 'name', ''))

    headers = [
        'sample_id', 'external_id', 'content', 'content_url',
        'status', 'consistency_score'
    ]
    if include_metadata:
        headers.extend(['version', 'created_at'])
    for name in label_names:
        headers.append(f'label_{name}')
    headers.extend(['annotator_count'])

    writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()

    for sample in samples:
        if isinstance(sample, dict):
            row = {
                'sample_id': sample.get('id'),
                'external_id': sample.get('external_id', ''),
                'content': (sample.get('content', '') or '')[:1000],
                'content_url': sample.get('content_url', ''),
                'status': str(sample.get('status', '')) if sample.get('status') else '',
                'consistency_score': sample.get('consistency_score', ''),
            }
            if include_metadata:
                row['version'] = sample.get('version', 1)
                row['created_at'] = str(sample.get('created_at', '')) if sample.get('created_at') else ''
            sid = sample.get('id')
            final_ann = sample.get('final_annotation') or {}
        else:
            row = {
                'sample_id': getattr(sample, 'id', None),
                'external_id': getattr(sample, 'external_id', ''),
                'content': (getattr(sample, 'content', '') or '')[:1000],
                'content_url': getattr(sample, 'content_url', ''),
                'status': str(getattr(sample, 'status', '')) if getattr(sample, 'status', None) else '',
                'consistency_score': getattr(sample, 'consistency_score', ''),
            }
            if include_metadata:
                row['version'] = getattr(sample, 'version', 1)
                row['created_at'] = str(getattr(sample, 'created_at', '')) if getattr(sample, 'created_at', None) else ''
            sid = getattr(sample, 'id', None)
            final_ann = getattr(sample, 'final_annotation', None) or {}

        for name in label_names:
            val = final_ann.get(name, '')
            row[f'label_{name}'] = _sanitize_value(val)

        row['annotator_count'] = len(sample_annotations.get(sid, []))

        writer.writerow(row)

    return output.getvalue()


def save_export_file(content: str, format: str, project_id: int) -> str:
    ensure_export_dir()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"project_{project_id}_{timestamp}.{format}"
    filepath = os.path.join(settings.EXPORT_DIR, filename)

    mode = 'w' if format in ('json', 'csv') else 'wb'
    if format in ('json', 'csv'):
        with open(filepath, mode, encoding='utf-8') as f:
            f.write(content)
    else:
        with open(filepath, mode) as f:
            f.write(content.encode('utf-8') if isinstance(content, str) else content)

    return filepath


def generate_filename(project_id: int, format: str) -> str:
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    ext = 'xlsx' if format == 'excel' else format
    return f"annotation_project_{project_id}_{timestamp}.{ext}"
