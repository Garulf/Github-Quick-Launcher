import requests_cache

from plugin import main


if __name__ == '__main__':
    requests_cache.install_cache(".cache", backend="sqlite", expire_after=300)
    main()
