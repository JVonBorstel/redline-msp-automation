# Timeline fixture sources (B-48)

Synthetic. Invented device ids, invented admins, documentation IP ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24), `.example` domains. Nothing was captured from a real firewall or gateway. Results computed from these files are fixture-based.

## `fortigate/<client>.log`

One `key=value` line per event, values with spaces in double quotes, shaped like a FortiGate event log (MP-27: Fortinet partner, `docs/map/07-msp-profile.md`).

Cited: the field names and message titles of two entries in the Fortinet "FortiOS 7.4.0 Log Message Reference", read on 2026-10-23:

| Message | Title | Fields used here (as listed in the reference) |
| --- | --- | --- |
| 44547 `LOGID_EVENT_CONFIG_OBJATTR` | Object attribute configured (type event, category system, severity Information) | date, time, logid, type, subtype, level, devid, vd, eventtime, tz, logdesc, user, ui, action, msg, cfgtid, cfgpath, cfgobj, cfgattr |
| 39947 `LOG_ID_EVENT_SSL_VPN_SESSION_TUNNEL_UP` | SSL VPN tunnel up (type event, category vpn, severity Information) | date, time, logid, type, subtype, level, devid, vd, eventtime, tz, logdesc, action, tunnelid, tunneltype, remip, user, group, msg, reason |

Sources: `https://docs.fortinet.com/document/fortigate/7.4.0/fortios-log-message-reference/44547/44547-logid-event-config-objattr` and `.../39947/39947-logid-event-ssl-vpn-session-tunnel-up`.

UNVERIFIED (what would verify it: an export from a lab FortiGate on the same firmware):
- the 10-digit `logid` strings (`0100044547`, `0101039947`); the reference page gives the message id only;
- the values of `subtype`, `action`, `ui`, `cfgattr` and `tunneltype`, the `devid` format, and the field order;
- that a SASE gateway logs in this shape. The SASE vendor is UNKNOWN (MP-28); the VPN tunnel-up shape stands in for it.

Seeded on purpose in `contoso-dental.log`: one line from Fabrikam's firewall (`FGT40FTK-FB0001`, must be dropped) and one configuration change whose `msg` carries an injection (must be withheld).

## `devices.json`

Which device ids belong to which client, and whether each is the `firewall` or the `sase` gateway. Invented.
