from app.realtime_caption import RealtimeCaption


def test_multiple_spoken_items_are_not_overwritten_by_last_done():
    caption = RealtimeCaption()
    for index, text in enumerate(['잠깐만요. 먼저 말씀드릴게요.', '안녕하세요! 반가워요.']):
        for chunk in [text[:4], text[4:]]:
            caption.update({'type':'response.output_audio_transcript.delta', 'output_index':index, 'content_index':0, 'delta':chunk})
        caption.update({'type':'response.output_audio_transcript.done', 'output_index':index, 'content_index':0, 'transcript':text})
    assert caption.text == '잠깐만요. 먼저 말씀드릴게요.\n안녕하세요! 반가워요.'


def test_response_summary_reconciles_without_duplicating_delta_text():
    caption = RealtimeCaption()
    caption.update({'type':'response.audio_transcript.delta','item_id':'a','delta':'안녕'})
    caption.update({'type':'response.done','response':{'output':[
        {'id':'a','content':[{'type':'audio','transcript':'안녕하세요.'}]},
        {'id':'b','content':[{'type':'audio','transcript':'좋은 하루예요.'}]},
    ]}})
    assert caption.text == '안녕하세요.\n좋은 하루예요.'
    assert len(caption.parts) == 2


def test_multiple_content_parts_and_empty_summary_keep_earlier_speech():
    caption = RealtimeCaption()
    for index, text in [(1,'두 번째'),(0,'첫 번째')]:
        caption.update({'type':'response.audio_transcript.done','content_index':index,'transcript':text})
    caption.update({'type':'response.done','response':{'output':[]}})
    assert caption.text == '첫 번째\n두 번째'


def test_streaming_provider_keeps_both_audio_items_in_final_caption(tmp_path):
    import asyncio
    import base64
    import json
    from app.conversation import OpenAIRealtimeConversation
    from app.models import AffectIntent
    class Socket:
        def __init__(self):
            self.events = []
            for index, text in enumerate(['먼저 길게 설명한 내용입니다.', '짧은 마지막 문장입니다.']):
                self.events.extend([
                    {'type':'response.output_audio_transcript.delta','output_index':index,'delta':text},
                    {'type':'response.output_audio.delta','delta':base64.b64encode(bytes(960)).decode()},
                    {'type':'response.output_audio_transcript.done','output_index':index,'transcript':text},
                ])
            self.events.append({'type':'response.done'})
        async def send(self, raw):
            pass
        async def recv(self):
            await asyncio.sleep(.001)
            return json.dumps(self.events.pop(0))
    async def check():
        provider = OpenAIRealtimeConversation('test','test',tmp_path)
        provider._sessions['s'] = provider._Session(Socket())
        response = await provider.respond(persona='test',user_text='test',session_id='s',turn_id='t',affect_override=AffectIntent(emotion='happy',intensity=1))
        assert response.audio_streaming
        for _ in range(100):
            state = provider.caption_status('s','t')
            if state and state[1]:
                break
            await asyncio.sleep(.005)
        assert state == ('먼저 길게 설명한 내용입니다.\n짧은 마지막 문장입니다.', True)
        assert list(provider.audio_dir.glob('*.pcm'))[0].stat().st_size == 1280
    asyncio.run(check())
