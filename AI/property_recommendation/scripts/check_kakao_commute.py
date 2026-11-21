from __future__ import annotations

import argparse
import asyncio
import json

from property_recommendation.kakao_commute import (
    KakaoCommuteConfig,
    KakaoCommuteProvider,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description="카카오 대중교통 연동 확인")
    parser.add_argument("workplace", help="도착지 이름 또는 주소")
    parser.add_argument("origins", nargs="+", help="출발 지역 또는 주소")
    parser.add_argument("--max-transfers", type=int)
    args = parser.parse_args()

    async with KakaoCommuteProvider(KakaoCommuteConfig.from_env()) as provider:
        metrics = await provider.measure_regions(
            args.workplace,
            args.origins,
            max_transfers=args.max_transfers,
        )
    print(
        json.dumps(
            {name: metric.model_dump() for name, metric in metrics.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
