"""Keep all spoken content parts, without duplicating delta + done text."""
class RealtimeCaption:
    def __init__(self):
        self.parts = {}

    def update(self, event):
        kind = event.get('type', '')
        if kind in {'response.done', 'response.completed'}:
            for index, item in enumerate(event.get('response', {}).get('output', [])):
                for content_index, part in enumerate(item.get('content', [])):
                    text = part.get('transcript') or part.get('text')
                    if isinstance(text, str):
                        self.parts[(index, content_index)] = text
            return
        if 'transcript' not in kind and kind not in {'response.output_text.delta', 'response.text.delta', 'response.output_text.done', 'response.text.done'}:
            return
        key = (event.get('output_index', 0), event.get('content_index', 0))
        if kind.endswith('.delta'):
            delta = event.get('delta')
            if isinstance(delta, str):
                self.parts[key] = self.parts.get(key, '') + delta
        elif kind.endswith('.done'):
            text = event.get('transcript') or event.get('text')
            if isinstance(text, str):
                self.parts[key] = text

    @property
    def text(self):
        return '\n'.join(text.strip() for _, text in sorted(self.parts.items()) if text.strip())
