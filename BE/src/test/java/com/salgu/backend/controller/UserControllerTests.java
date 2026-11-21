package com.salgu.backend.controller;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.oauth2Login;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.salgu.backend.domain.User;
import com.salgu.backend.repository.UserRepository;
import com.salgu.backend.service.UserService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

@SpringBootTest
@AutoConfigureMockMvc
class UserControllerTests {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private UserService userService;

    @Autowired
    private UserRepository userRepository;

    @Test
    void meRequiresLogin() throws Exception {
        mockMvc.perform(get("/api/me")).andExpect(status().isUnauthorized());
    }

    // runs against the real DB: @Transactional rolls the rows back, negative id never clashes with Kakao ids
    @Test
    @Transactional
    void kakaoLoginCreatesThenUpdatesUser() throws Exception {
        userService.loginWithKakao(-1L, "salgu");
        userService.loginWithKakao(-1L, "salgu2");

        assertThat(userRepository.findByKakaoId(-1L)).get()
                .extracting(User::getNickname).isEqualTo("salgu2");
        mockMvc.perform(get("/api/me").with(oauth2Login().attributes(a -> a.put("sub", "-1"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.nickname").value("salgu2"));
    }

    @Test
    void logoutReturnsOk() throws Exception {
        mockMvc.perform(post("/logout").with(oauth2Login())).andExpect(status().isOk());
    }
}
