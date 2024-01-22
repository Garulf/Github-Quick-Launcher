from typing import Tuple

from pyflowlauncher.result import ResultResponse, send_results

from results import context_menu_results


def context_menu(data: Tuple[str, str]) -> ResultResponse:
    return send_results(context_menu_results(*data))

