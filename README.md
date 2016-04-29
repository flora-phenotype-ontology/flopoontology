Project to identify phenotypes occurring in flora files.

There are three components:

1. ParseFloraFile is the original piece of code generated at the pro-iBiosphere Hackathon in Leiden. It will find PO and PATO terms in flora gabon and malaysia.
2. Lucene-based indexing: this is a refactoring of the original code that uses the Lucence indexes and analyzers.
3. MakePlantPhenotypeOntology generates a phenotype ontology from the generated descriptions.
4. DeprecateDumbClasses deprecates all unsatisfiable classes; this script needs to be run after adding axioms (e.g., a GCI) that makes classes that could not exist in FLOPO unsatisfiable. Useful when adding `has-part some (owl:Thing and has-quality some 'process quality') SubClassOf: owl:Nothing` or similar axioms.

The resulting ontology is available under a CC-0 license in the `ontology` folder. All code is available under the BSD license.
