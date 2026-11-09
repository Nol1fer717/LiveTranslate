"""Experimental local speaker turns using pyannote segmentation and WeSpeaker."""
import numpy as np
import sherpa_onnx as so

RATE = 16000
UNKNOWN = 'Голос не определён'


class SpeakerDiarizer:
    def __init__(self, data):
        embedding = str(data / 'wespeaker-resnet34.onnx')
        config = so.OfflineSpeakerDiarizationConfig(
            segmentation=so.OfflineSpeakerSegmentationModelConfig(
                pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(data / 'speaker-segmentation.onnx'), window_shift_ratio=0.1), num_threads=2),
            embedding=so.SpeakerEmbeddingExtractorConfig(model=embedding, num_threads=2),
            clustering=so.FastClusteringConfig(num_clusters=-1, threshold=0.8),
            min_duration_on=0.3, min_duration_off=0.5)
        if not config.validate():
            raise RuntimeError('Не удалось загрузить модели различения голосов')
        self.diarizer = so.OfflineSpeakerDiarization(config)
        self.extractor = so.SpeakerEmbeddingExtractor(so.SpeakerEmbeddingExtractorConfig(model=embedding, num_threads=2))
        self.centres = []

    def label(self, samples):
        if len(samples) < RATE:
            return UNKNOWN
        stream = self.extractor.create_stream()
        stream.accept_waveform(RATE, samples)
        stream.input_finished()
        if not self.extractor.is_ready(stream):
            return UNKNOWN
        vector = np.asarray(self.extractor.compute(stream), dtype=np.float32)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            return UNKNOWN
        vector /= norm
        scores = [float(c @ vector) for c in self.centres]
        if scores:
            best = int(np.argmax(scores))
            if scores[best] >= 0.6:
                if len(scores) > 1 and scores[best] - sorted(scores)[-2] < 0.08:
                    return UNKNOWN
                centre = self.centres[best] * 0.8 + vector * 0.2
                self.centres[best] = centre / np.linalg.norm(centre)
                return f'Голос {best + 1}'
            if scores[best] > 0.4:
                return UNKNOWN
        self.centres.append(vector)
        return f'Голос {len(self.centres)}'

    def turns(self, samples):
        if len(samples) < RATE:
            return []
        rows = self.diarizer.process(samples).sort_by_start_time()
        grouped = {}
        for row in rows:
            # Exclude overlapping regions from identity embeddings.
            a, b = max(0, int(row.start * RATE)), min(len(samples), int(row.end * RATE))
            mask = np.ones(max(0, b - a), dtype=bool)
            for other in rows:
                if other.speaker != row.speaker:
                    x, y = max(a, int(other.start * RATE)), min(b, int(other.end * RATE))
                    if y > x:
                        mask[x-a:y-a] = False
            grouped.setdefault(row.speaker, []).append(samples[a:b][mask])
        names = {key: self.label(np.concatenate(parts)) for key, parts in grouped.items()}
        return [(row.start, row.end, names[row.speaker]) for row in rows]
