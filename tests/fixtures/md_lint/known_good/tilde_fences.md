A tilde-fenced code block:

~~~bash
echo "this `looks unbalanced` but is inside a tilde fence"
echo `another stray backtick run that should not trip`
~~~

After the fence, balanced again: `ok`.
