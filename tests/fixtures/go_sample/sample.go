// Compact Go fixture exercising every node/edge shape the extractor emits.
// Intentionally tiny so test assertions stay focused.

package sample

import (
	"fmt"
	"strings"

	custom "github.com/example/foo"
	_ "github.com/example/driver"
)

// Greeter is a simple struct, used to verify CLASS-node emission.
type Greeter struct {
	Prefix string
}

// Polite embeds Greeter — should produce an INHERITS edge.
type Polite struct {
	Greeter
	Suffix string
}

// Greetable is an interface (also captured as a CLASS-kind node for now).
type Greetable interface {
	Greet(name string) string
}

// Greet is a method on Greeter — METHOD node with receiver Greeter.
func (g *Greeter) Greet(name string) string {
	return fmt.Sprintf("%s %s", g.Prefix, name)
}

// Shout is a method on the same receiver, calling Greet — exercises
// intra-type method calls (resolver should hook receiver.Greet → Greeter.Greet).
func (g *Greeter) Shout(name string) string {
	out := g.Greet(name)
	return strings.ToUpper(out)
}

// NewGreeter is a top-level FUNCTION constructing the struct.
func NewGreeter(prefix string) *Greeter {
	return &Greeter{Prefix: prefix}
}

// Run is a top-level FUNCTION calling other top-level functions plus
// imported packages — exercises bare-name, dotted-package, and method calls.
func Run() {
	g := NewGreeter("hi")
	msg := g.Greet("world")
	custom.DoThing(msg)
	fmt.Println(msg)
}
