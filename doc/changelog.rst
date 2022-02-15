##############
Changelog
##############

v 0.0.6 - 2022-02-15
====================
* Fixed improper cleanup on client disconnection that resulted in growing server memory and CPU usage.


v 0.0.5 - 2022-01-03
====================
* Added support for iterator methods :meth:`ttdoc:Counter.getDataObject()`.
* Implemented support for :meth:`ttdoc:SynchronizedMeasurements.getTagger()`.
* Improved logging.
* Renamed root Pyro object `TimeTagger` to `TimeTaggerRPC`.
* Typo corrections in the documentation.
* Added this changelog.
