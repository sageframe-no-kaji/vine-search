# Optional notifications

The dashboard works with notification delivery disabled. Enabling webhook or
ntfy sends selected matching product or review-reminder metadata to the configured
destination. Choose a destination you operate or trust; its operator can see the
message contents. Destination URL and bearer token are write-only in normal APIs.

Save the destination, enable delivery, then use Send test. Activity records the
queued/sent/failed outcome. The initial catalog and existing products at rule
changes are baselined. Default deduplication alerts once per product/tracker;
relist alerts are an explicit option. Quiet hours use the selected IANA timezone.
Equal start/end times disable the quiet interval.

## Self-hosted ntfy

Run ntfy on an operator-controlled host and protect its topics with authentication.
A minimal Compose service can use the maintained `binwiederhier/ntfy` image,
a persistent `/var/lib/ntfy` mount and `serve` command. Configure `base-url`,
an authentication database, and `auth-default-access: deny-all`, then create an
operator account/topic token. Use the full topic URL as VineSearch's destination
and the token in its separate secret field.

The ntfy project's [configuration guide](https://docs.ntfy.sh/config/) documents
server authentication and reverse proxies. Follow its current image/version
instructions when deploying the optional service.

For instant iOS delivery from a self-hosted ntfy server, ntfy documents an upstream
wake-up relay through ntfy.sh/APNs. This creates an external notification path even
when the message server is local. Review the
[iOS relay behavior](https://docs.ntfy.sh/config/#ios-instant-notifications) before
enabling it; an installation without that relay does not have the same instant
background-delivery behavior.

## Webhook

The adapter POSTs JSON with a bounded timeout and no redirects. Local network
destinations are permitted because self-hosted receivers are supported. Only the
operator can configure a destination, through protected settings.

Delivery is at least once; the stable outbox identity supports receiver-side
deduplication after uncertain network outcomes. Failures use bounded exponential
backoff and stop after five attempts. Test delivery uses the configured
destination and appears in Activity; real external testing requires an explicitly
supplied destination.
