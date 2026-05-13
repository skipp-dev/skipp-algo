Backtick-fenced code block with cross-line content:

```bash
echo "this `unbalanced span` lives inside the fence"
gh run view 123 --log \
  | grep -E 'Step [0-9]+' \
  | head -20
```

Inline after fence stays clean: `ok`.
