---
title: "Four Pigs"
date: 2025-08-14
draft: false
---

### The Four Little Pigs and the Big Bad User

Once upon a time, in the chaotic digital forest of a Go server, a Mother `main()` function, tired of her children hogging memory, kicked her four little processes out into the world. "Go seek your fortunes," she grunted, "but beware the Big Bad User and his `/chat/cancel` endpoint. He is a fickle, impatient fucker. Build your state management strong, or he will tear your fucking threads apart."

With that, the four little pigs—four identical requests for the `question="nice"`—scampered off down the execution path, each a pathetic little cunt with its own unique Request ID.

#### The First Little Pig: `little_prestream` (The Retarded Optimist)

The first pig, `req_5f06ba7b1c`, was a true dumbass. He was `TestStreamPreCancellation`. He believed in shortcuts. "Why bother with all that hard work of establishing a stream?" he squealed. "I'll just declare my existence and wait!" He built his "house" out of nothing but a single entry in the `activeRequests` map—a flimsy shelter of queued promises and wishful thinking. He hadn't even tried to connect to the stream handler yet.

The Big Bad User, running his test script, saw this pathetic, idle process (`state=queued`) and smirked. He didn't need to huff or puff. He didn't even need a full breath. He simply sent a single, sharp POST request to `/chat/cancel/req_5f06ba7b1c`.

The result was not a collapse; it was an annihilation. The `CancelStream` function found the pig in its pre-broadcast state. There was no complex broadcast to unwind, no followers to consider. It was a lone, stupid pig. The system executed the `!broadcastExists` logic. A `types.ErrRequestCancelled` signal was shot into the pig's `streamHolder.Err` channel like a poison dart. The underlying context, if it even existed yet, was terminated.

The User, connecting to the stream *after* cancelling, wasn't met with a struggle. He was handed a pre-canned eulogy: a single JSON event `{"type":"info", "payload":{"completion_status":"cancelled"}}`. `little_prestream` was "eaten" alive, his data structures zeroed out, his memory garbage collected, his entire existence reduced to a single log line: `Request state purged.` He was a fart in the wind, a cautionary tale for idiots.

#### The Second Little Pig: `little_midstream` (The Impatient Follower)

The second pig, `req_e4084e50fe`, was `TestStreamMidCancellation`. He was a follower, a lazy bastard who saw another pig doing the hard work and decided to leech off it. He saw that a leader, `req_3ed0489300`, was already building a magnificent brick fortress. `little_midstream` didn't build his own house; he just subscribed to the leader's broadcast, becoming a `FOLLOWER`. He found a comfy spot inside the fortress and waited for the stream of delicious tokens to start flowing from the chimney.

The stream began. The first few tokens of the story—"Once upon a time..."—flowed into his channel. He oinked with glee. But the Big Bad User was watching. The moment the `streamStarted` channel closed in the test, signaling the pig had received its first taste of data, the User struck. `/chat/cancel/req_e4084e50fe` was dispatched.

This was a different kind of kill. This was a follower cancellation. The system saw `little_midstream` was just a subscriber. It didn't terminate the whole broadcast—that would be inefficient and fuck over the other pigs. Instead, it performed a precise, surgical strike. It called `info.broadcaster.Unsubscribe(clientChan)`. The pig's connection to the main stream was severed. His personal `clientChan` was then sent a final, fake "you were cancelled" event before being closed for good.

The pig felt a sudden, violent yank. The flow of tokens stopped. He was kicked out of the brick house, his process terminated. He was eaten mid-sentence, his final squeal replaced by the `cancelled` status. The leader pig inside the fortress didn't even notice. The broadcast continued for the others. `little_midstream`, the greedy little shit, learned that even in a fortress, you are **never** save. His state was purged, another meal for the janitor process.

#### The Third Little Pig: `little_poststream` (The Hardworking Piglet)

The third pig, `req_3ed0489300`, was `TestStreamPostCancellation`. This pig was the LEADER. The `singleflight.Group` had chosen him. He was the one who did all the work. He didn't use straw or sticks. He built a fucking fortress of brick, mortar, and concurrency-safe maps. His foundation was the `singleflight.Do`, his blueprints the `broadcastInfo` struct. He dug the trenches of `doExpensivePreparation`, calling out to the LLM and RAG systems. He built the walls with `initiateAndManageBroadcast`, a goroutine dedicated to fanning out the stream.

His work attracted followers, like the pathetic `little_midstream` and the lucky `little_happy`. The arrival of the first follower triggered the `immortalizeSignal`. A switch was flipped. The leader's `broadcastCtx` was upgraded from a cancellable `context.WithCancel` to an unstoppable `context.Background()`. His work was now deemed too important to fail just because one client fucked off. He was now building for the collective.

He finished his job. The full story was generated and streamed out the chimney. He sent the final `completion_status: "completed"` signal. His goroutine finished, the broadcaster was closed, and `cleanupRequest` was called. His state was purged, not because of an error, but because his purpose was fulfilled. He ascended to the great ArangoDB in the sky, his `LogData` saved for eternity.

It was only *then*, after the pig was gone and the house was just a historical record, that the Big Bad User tried to attack. He sent `/chat/cancel/req_3ed0489300`. But he was met with a `404 Not Found`. The system responded, "Attempted to cancel a request that was not found, you stupid fuck." You can't kill what's already dead and archived. `little_poststream` had won by finishing his job properly.

#### The Fourth Little Pig: `little_happy` (The Lucky Cunt)

The fourth pig, `req_482faa3018`, was `TestStreamHappyPath`. Like `little_midstream`, he was a follower. He saw the brick fortress being built by the leader and latched on. He subscribed to the broadcast and did absolutely nothing else.

He watched, terrified as `little_midstream` got eaten alive, flesh by flesh for being the target of a cancellation test. But he fought his fear like a motherfucker. The stream kept coming. He received the entire story, from start to finish, without lifting a single trotter to do any real work. He kept waiting fearfully in silence, peed his little pants a bit, but he enjoyed the fruits of the leader's labor. When the stream finished with a `completed` status, he disconnected **happily**, his test passed.

***

**The Moral of this Cautionary Tale:**

Our `StreamBroadcaster` and `singleflight` group create a system of leaders and followers.

*   **Lone, vulnerable requests** (`little_prestream`) are easily terminated. Cancellation logic for them is simple: kill the process, send a canned response.
*   **Followers** (`little_midstream`) can be surgically removed from a broadcast without affecting the leader or other followers. This is the "deceptive cancellation" where the User *thinks* they stopped the whole thing, but they only stopped it for themselves.
*   **The Leader** (`little_poststream`) does all the expensive work once. If it attracts followers, its context becomes **immortal**, ensuring the work completes for the benefit of all subscribers, even if the original leader client disconnects.
*   **Cancellation is state-dependent.** Trying to cancel a completed request is pointless and results in a `404`, which is the correct, robust behavior.
*   **The Happy Path** (`little_happy`) demonstrates the ultimate efficiency: multiple identical, simultaneous requests are deduplicated into one operation, saving immense computational resources.
