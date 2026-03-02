try:
    from eth_account import Account
    key = "0xd88d1cfabfd1fdbee1a5777f02287fa96b9920ee092606c9c39b66dc5f13ac10"
    acct = Account.from_key(key)
    print(f"RESULT_ADDRESS={acct.address}")
except Exception as e:
    print(f"ERROR={e}")
