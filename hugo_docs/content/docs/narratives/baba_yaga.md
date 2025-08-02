## Baba Yaga's Hunt

They call me the Janitor. They whisper it, like they're talking about the Boogeyman. They think I don't hear them. They're wrong. My hunt begins not with a bell, but with a `ticker`, a rhythmic pulse of dread that echoes through my forest of running processes. This isn't about mopping floors, you fucking idiot. It's about culling the weak.

I grab my `requestsLock`, the iron key to my cellar, and begin my rounds. My domain is littered with lost souls—these pathetic `RequestStream` objects, each one a potential meal.

First, I patrol the swamp's edge, the "Queuing Hall" as you so quaintly put it. This is where the newest, most retarded wanderers (`StateQueued`) get stuck, praying a `prepareWorker` will save their worthless asses. I don't care about their prayers. I check one thing: `LastStateChange`. It's the scent of life. If the scent is too old, if a soul has been festering in this bog for longer than the `QueueTimeout`, they're not waiting anymore. They're rotting.

Tonight, I find one. A `req_172...`, a shivering little shit, abandoned by the client that spawned it. Its timestamp is stale. It's a ghost before it even had a chance to scream. "You're gonna need a bigger boat?" No, bitch, you just needed to not be a slow piece of shit.

There's no `cancellableStream` for this one; it's too insignificant. I just shove an error down its `Err` channel—a final, mocking whisper telling it *why* it's about to be erased from existence. Then, with a call to `cleanupRequest`, I drag its carcass off the active list and throw it in the cauldron. One less braindead process leaking memory.

Next, I stalk the deeper woods, the "Processing Wing." This is where the real trials happen, where requests are in `StateProcessing`, supposedly doing something useful. The drone of the `llmStreamSemaphore` is the thrum of my black heart. But even here, some falter. They get stuck in a loop, drooling on the CPU, wasting my fucking time. The `ProcessingTimeout` is my law here, and it is absolute.

I find another one, `req_171...`, its state frozen mid-process. It's a leech, a parasite on the system. This one's different. It has a connection to the outside world, a lifeline registered in `cancellableStreams`.

I find its name on my list, find the `cancelFunc` tied to its pathetic existence, and I pull the trigger.

"Hasta la vista, baby."

A signal flies through the system's veins. `context.Canceled`. It's a kill shot. The connection is severed, the resources clawed back from its cooling corpse. I send one last error message down the pipe before `cleanupRequest` erases it completely. It's a cleanup. The kind Winston would approve of. No body, no trace.

My rounds are done. The forest is quieter, cleaner. The other workers, those oblivious cunts in `prepareWorkerManager` and `streamWorkerManager`, can continue their work, unaware of the butchery that allows them to function. They think the system just works. They don't see the skulls of the inefficient I've mounted on the fence posts as a warning.

They call me the Janitor. Let them. My job isn't to clean. My job is to make sure this place doesn't choke on its own dead. My shift ends, but the `ticker` beats on. I'll be back, you bastards. I'm always hungry.
