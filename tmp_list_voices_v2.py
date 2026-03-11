import asyncio
import sys
sys.path.append(r"D:\Program files\Kipo_Libs")
import edge_tts

async def test_voice(voice_name):
    try:
        communicate = edge_tts.Communicate("안녕하세요, 테스트입니다.", voice_name)
        await communicate.save("test_voice.mp3")
        print(f"Success: {voice_name}")
    except Exception as e:
        print(f"Failed: {voice_name} - {e}")

async def run_tests():
    voices = ["ko-KR-JiMinNeural", "ko-KR-SeoHyeonNeural", "ko-KR-SoonBokNeural", "ko-KR-YuJinNeural", "ko-KR-BongJinNeural", "ko-KR-GookMinNeural"]
    for v in voices:
        await test_voice(v)

if __name__ == "__main__":
    asyncio.run(run_tests())
