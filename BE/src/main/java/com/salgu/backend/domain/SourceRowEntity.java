package com.salgu.backend.domain;

import jakarta.persistence.Id;
import jakarta.persistence.MappedSuperclass;
import java.time.OffsetDateTime;
import lombok.Getter;

/** Common tracking columns present on every imported public-data table. */
@Getter
@MappedSuperclass
public abstract class SourceRowEntity {

    /** Row number inside the source snapshot. Not a stable business ID. */
    @Id
    private Long sourceRow;

    private String sourceFileSha256;

    private OffsetDateTime importedAt;
}
