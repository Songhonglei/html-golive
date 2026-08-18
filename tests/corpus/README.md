# Scanner corpus

Sample pages the credential scanner is measured against.
`tests/test_scanner_corpus.py` walks these directories, so adding a case
means adding a file — no test code to edit.

```
must_block/   contains a real credential; publishing it must be refused
must_pass/    contains no credential; must publish without a BLOCK
```

## Adding a case

Drop an `.html` file into the right directory with a name that says what it
covers (`aws_access_key.html`, `base64_image.html`). Then run:

```bash
python3 -m pytest tests/test_scanner_corpus.py -v
```

`must_pass` is as important as `must_block`. A scanner that cries wolf gets
routed around — someone will reach for `--skip-content-scan` out of habit, or
stop using golive for the page that actually matters. Every false positive
fixed here is a real one caught later.

## Writing the samples

Assemble the secret from fragments so this repository does not itself carry a
literal credential:

```html
<p>key: sk-<!-- split -->0123456789abcdefghij</p>
```

Use obviously fake values. Never paste a real key, even a revoked one.
