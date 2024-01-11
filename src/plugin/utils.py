def strip_keywords(query, keywords):
    for key in keywords:
        if query.startswith(key):
            query = query[len(key):]
            break
    return query.lstrip()